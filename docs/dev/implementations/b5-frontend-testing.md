# B5 — frontend testing

**Status:** Code review
**Date:** October 16, 2026
**Author model:** Claude Sonnet 5.5
**Reviewer model:** Claude Opus 5.5 (plan review round 1; code review round 1 pending)
**Spec:** `docs/dev/alpha-build-plan.md` §6 B5 and §3 ("ALWAYS write tests first"); `docs/references/nextjs-style-guide.md` ("Testing" and the
Anti-patterns table); `docs/arch/arch-initial.md` §4 (libraries table: `vitest`, `@testing-library/react`; filter and view
state in the URL); `docs/arch/requirements-initial.md` ("Calendar": the filter header, "No matches found" with a reset
link); `apps/calendar/AGENTS.md`; `AGENTS.md` ("Conventions": *Tests state what they prove*, "[fill-in] tasks");
`docs/dev/implementations/b2-routes-and-data-loading.md`, `b3-the-calendar.md` and `b4-detail-pages.md`, whose
"What is *not* covered" lists and "Follow-ups" are B5's inbox

## Context

B1 installed Vitest (node environment) and wired it into Turbo, `make test` and CI. B2, B3 and B4 then unit-tested every
piece of logic they could reach as a pure function in `lib/` (**283 tests in 14 files**, measured on the unmodified
repo), and each ended with a "What is *not* covered, stated plainly" list that deferred the same thing to B5: the
components. B3 said it outright: "the filter header is the first component test target."

What exists, what the build plan asks for, and what B5 does about it:

| Build-plan item | Today | B5 |
|---|---|---|
| `vitest` + `@testing-library/react` set up **[written]** | Vitest runs in the node environment; no Testing Library, no jsdom; a `.test.tsx` file **cannot even be parsed** (Checked, fact 1) | Five dev dependencies, a JSX setting, two Vitest projects and a setup file (step 1) |
| Component tests: **the filter header** **[fill-in]** | `app/_components/filter-header.tsx`, a Client Component; no test | `filter-header.test.tsx` (steps 3–4; gaps K1, K2) |
| Component tests: **the empty state** | Two inline messages inside `CalendarBody`, an **async** Server Component that the style guide says not to unit-test | Pull the sync part out as `CalendarResults` (D1), then test it (step 5; gap K3) |
| Component tests: **the date grouping** | `groupCalendar` is a pure function with 14 tests already (`lib/calendar.test.ts`); what is untested is how `CalendarGrid` *renders* a row | `calendar-grid.test.tsx` and one integration test through `groupCalendar` and the 25-show fixture (step 5) |
| **Deferred:** Playwright | Not installed | Still deferred (Not doing) |

What B5 is *not*: a test of any `async function Page()` (style guide, Testing: "push that coverage to Playwright"), of the
shadcn primitives in `packages/ui` beyond what the filter header exercises, or of anything that needs a real router.
Production code changes only where a named test target cannot be reached without it: D1 (an extraction) and D3 (an
accessible name).

### Decisions already made (earlier in this project)

- **Async Server Components are not unit tested; Vitest + Testing Library is for "pure functions, … small sync
  components"** (style guide, Testing). B5 draws the line there, which is why D1 exists.
- **Tests state what they prove** (`AGENTS.md`, Conventions): each test opens with a `Proves:` comment, tests sit under
  labelled section comments, helpers are explained, and expected values say where they come from. A test that reads its
  expectation from the code under test cannot catch that code being wrong.
- **Filter state lives in the URL** (`arch-initial.md` §4; B3-D8: `push`, not `replace`). So for the filter header
  the pushed URL *is* the behaviour, and the tests assert on it.
- **A Client Component imports only from `lib/calendar-href.ts`**, never `params.ts` or `dates.ts` (the Temporal bundle
  check, `apps/calendar/AGENTS.md`). Any helper the header needs goes there (D1's `hasActiveFilters`).
- **B4 already decided** that `WindowNav` and the day view's mode switch are plain links in Server Components and need
  no component test (B4's follow-ups); `show-order.ts` and `calendar-window.ts` are unit tested.
- **Every route is dynamic and nothing is cached** (B2-D1). Unchanged; B5 adds no route.

## Checked before planning

Everything below was run in a **throwaway `git worktree`** (installed with `pnpm install --frozen-lockfile`, the new
packages added there only), on this sandbox's Node 22.22.0, against the API served from `sample_data.py`. The real
working tree was never touched. CONFIRMED means the command was run and the output read.

| # | Fact | Evidence | Consequence |
|---|---|---|---|
| 1 | **The current config cannot run a component test.** A `.test.tsx` file fails at parse time: `Unexpected JSX expression` | CONFIRMED. `packages/typescript-config/nextjs.json` sets `"jsx": "preserve"` (Next compiles JSX itself); Vite 8 transforms with Oxc, which honours it and leaves JSX untransformed | `vitest.config.ts` needs `oxc: { jsx: { runtime: "automatic" } }`. This is also step 1's red state |
| 2 | **jsdom's newest major (30.1.3) needs Node `^22.22.2 \|\| ^24.15.0 \|\| >=26.0.0`**; the sandbox has 22.22.0, which is below the first. jsdom 29.1.1 needs `^20.19.0 \|\| ^22.13.0 \|\| >=24.0.0`; CI's `node-version: 24` resolves to the newest 24.x | `npm view jsdom@30 engines`; jsdom 29 ran every test on this Node | Pin `jsdom@^29`. The repo's floor is already ≥ 22.12 through Vitest 5 itself (`^22.12.0 \|\| ^24 \|\| >=26`), so no `engines` change. A Dependabot bump to 30 will very likely pass CI and fail a cloud session or a laptop on an older 24.x; the full range goes in `notes.md` |
| 3 | `@testing-library/dom` is a **peer** of `@testing-library/react` 16.3.3, so it must be installed explicitly | `npm view @testing-library/react peerDependencies` | Five packages, not four: `jsdom`, `@testing-library/{react,dom,user-event,jest-dom}` |
| 4 | **Two Vitest projects work side by side.** `*.test.ts` stays in the node environment (`typeof document === "undefined"` is true inside it), `*.test.tsx` runs in jsdom; the `@` and `server-only` aliases carry over with `extends: true` | CONFIRMED: all 14 existing files (283 tests) passed in the `unit` project beside a jsdom project | The file extension picks the environment. No docblock to forget |
| 5 | Testing Library's **automatic cleanup needs `afterEach` as a global**, and this repo does not enable Vitest globals | CONFIRMED: two tests each rendering `<p>one</p>` pass only with a setup file calling `cleanup()` | `test/setup-dom.ts` does `afterEach(() => cleanup())` and loads jest-dom's matchers |
| 6 | **The real `FilterHeader` renders and works in jsdom with exactly one mock**, `next/navigation`'s `useRouter`. Base UI's combobox and select, `next/link`, `@repo/ui` (TS source through the package `exports`) and the Temporal polyfill need nothing | CONFIRMED: 10 prototype interaction tests passed with no `act()` warnings, and one went red when its expected URL was deliberately wrong | The mock sits at the framework's edge and nothing else is faked |
| 7 | **`fireEvent.click` never opens the combobox**: no option appears even after waiting. `userEvent` does, and after an awaited `user.click` the option is already in the DOM (a synchronous `getByRole` works; `findByRole` is the tolerant default) | CONFIRMED (three probes) | `@testing-library/user-event` is required, not a nicety. K2's lesson |
| 8 | With no mock, `FilterHeader` dies with `invariant expected app router to be mounted`. A `vi.mock` factory that reads a top-level `const` eagerly dies with `Cannot access 'push' before initialization` | CONFIRMED | K1's lesson and its likeliest mistake |
| 9 | **Colocated tests are safe for the app.** With `.test.tsx` files in `app/_components/` *and* `app/error.test.tsx` next to the special `error.tsx`, `next build` (API unreachable) prints the same nine routes, all `ƒ`; `pnpm check-types` passes (jest-dom's types arrive through the setup file); `pnpm lint --max-warnings 0` reports nothing on app or lib code | CONFIRMED | Tests sit beside what they test, as `lib/*.test.ts` already do |
| 10 | **Every chip "remove" button has no accessible name** (checked with one chip and with two): text empty, `aria-label` null, and none matched by `getByRole("button", { name: /.+/ })`. A screen reader announces each as just "button" | CONFIRMED. `ComboboxChip` in `packages/ui/src/components/combobox.tsx` renders `ChipRemove` with only an `<XIcon>` and passes no label | D3. A user-style query cannot find the control that removes a chip |
| 11 | A 3-line fix works: `ComboboxChip` gains an optional `removeLabel` that becomes the remove button's `aria-label`, and `FilterHeader` passes `` `Remove ${o.name}` `` | CONFIRMED: `getByRole("button", { name: "Remove Zhora Darling" })` finds it, the push is `/?venue=1`, typecheck passes | D3's recommendation |
| 12 | **`Updating…`, `aria-busy` and the optimistic chip cannot be observed under a mocked router.** After a pick, `aria-busy` is `"false"` and the status text is empty at once, because the mocked `push` returns immediately and the transition ends | CONFIRMED | Stated under "What is not covered"; it is Playwright's |
| 13 | **The D1 extraction is behaviour-preserving**: the rendered `<main>` of `/`, `/?venue=1`, `/?venue=2&artist=7`, `/?month=2027-01`, `/?venue=abc`, `/?month=2026-10` is byte-identical before and after, in headless Chromium (`--dump-dom`) | CONFIRMED, with sanity columns: 25 / 8 / 1 / 0 / 25 / 23 articles, skeleton count 0 | Verification 4's method. **Two methods that look equivalent are not:** comparing raw server HTML differs by streaming order even for identical content (Suspense chunks arrive in whatever order the five parallel API calls return), and jsdom with scripts enabled never runs Next's `$RC` swap, so it "agrees" on two skeletons (articles 0, skeleton 1: a false positive caught only by the sanity columns) |
| 14 | The **unfiltered-empty branch is unreachable through sample data** (its default window always has shows), so no HTTP check or browser visit can see "No shows listed for these dates." | CONFIRMED by the matrix in 13: every sample URL either has shows or carries a filter | The component test is that branch's only check |
| 15 | **Prototype tests with K1–K3 filled in go green on the real components and red under 8 targeted mutations**, each caught by the test this plan names for it (Verification 3) | CONFIRMED: M1–M8 all RED, every file restored | The gap snippets fit, and the tests can fail |

## Departures from the build plan (to apply to `alpha-build-plan.md` when implementing)

1. **The setup item is larger than its wording.** "Still to do here: `@testing-library/react` and jsdom" becomes five
   packages (fact 3), the Oxc JSX setting (fact 1), two projects and a setup file (facts 4–5).
2. **"The date grouping" is already unit tested** as `groupCalendar` (14 tests). B5 does not re-test the function; it
   tests what the grid does with its rows, and runs one integration through `groupCalendar` and the fixture.
3. **"The empty state" is not a component today**; it is two inline paragraphs in an async component. D1 extracts it.
4. **Added, not in the build plan:** `ShowBlock` and three small "pin" tests (D2), and the chip-remove accessible name (D3).
5. **Marking.** The setup is [written]; the component tests stay [fill-in] with three gaps (K1–K3); everything else is
   [written]. Every gap is test code, which is unusual: the lesson in a test-writing milestone is in the tests.

## Decisions for Ari

**Settled by Ari, October 16, 2026: D1–D4 are accepted as recommended, and the plan is approved for implementation.** Each decision below keeps its recommendation and its alternative on record.

- **D1 — Extract `CalendarResults` (a sync component) and `hasActiveFilters` (a pure helper). Decided: yes (recommended).**
  The empty state is the build plan's second named test target, and it cannot be tested where it lives: both messages
  sit inside `CalendarBody`, which `await`s five API calls. The extraction moves the `shows.length === 0 ? … : <grid>`
  branch into `app/_components/calendar-results.tsx` (props `start`, `end`, `shows`, `today`, `filters`; no fetching),
  and the "is anything filtered" expression, which exists **twice** today (`app/page.tsx:72` and
  `filter-header.tsx:93`), into `hasActiveFilters(filters)` in `lib/calendar-href.ts` (Temporal-free, so the Client
  Component may import it). `CalendarBody` keeps the fetching, the `today` computation and the "Showing …" line.
  Evidence the move is safe: fact 13 (identical rendered `<main>` for six URLs). Cost: one new component and one helper;
  `page.tsx` gets shorter. *Alternative:* leave the page alone, test only `CalendarGrid`, and leave the empty state to
  Playwright (the build plan's named item is then not met, and "No matches found" has no check until then).
- **D2 — Scope beyond the three named targets. Decided: add `ShowBlock` and three "pin" tests (recommended).**
  `ShowBlock` is the grid's cell and holds the render layer's densest logic (seven branches: time link vs. "Details"
  link, an end time with no start, `withVenue`, per-act times only on multi-act bills, and "price not stated is *not* free").
  The pins each guard a property whose loss would be silent: `ErrorPage` never prints `error.message` (B2's server-log
  reasoning), `RemoteImage` renders nothing for a non-http(s) URL and sets `no-referrer` (B4-D4), and `JsonLd` cannot be
  closed early by a `</script>` in scraped text (B4). Together about twenty tests, kept in their own steps (6 and 7) so
  dropping either is a deletion. *Alternative:* only the three named targets, and the rest stay in "Not covered".
- **D3 — Give the chip-remove buttons an accessible name now. Decided: fix, test first (recommended).**
  Fact 10 is a real defect in the shipped UI that this milestone's own tooling found: the primary way to un-pick a
  filter is a button a screen reader calls "button". The fix is 3 lines in the shared `combobox.tsx` (an optional
  `removeLabel`) and 1 in `FilterHeader` (fact 11), written as a failing test first. It also lets the test suite cover
  chip removal by role and name instead of by position or `data-slot`. It touches `packages/ui`, which is the cost.
  *Alternative:* leave the UI alone, record the gap in `notes.md`, and mark the test `it.todo("names each chip's remove
  button")` so it shows in every run; chip removal is then tested only through the option list (which works: it is test 5).
- **D4 — Include `@testing-library/jest-dom`. Decided: yes (recommended).** It gives `toBeInTheDocument()`, `toHaveAttribute()` and
  `toHaveTextContent()` with failure messages that print the element (`expected element to have attribute href="/"`,
  received the actual attributes), and it is what Testing Library's own docs assume. Cost: one more dev dependency and a
  type augmentation through the setup file (fact 9 shows it type-checks). *Alternative:* plain DOM assertions
  (`expect(el.getAttribute("href")).toBe("/")`, `expect(queryBy…).toBeNull()`): one fewer package, noisier failures.

## Test approach (written first, watched fail, then made green)

### Ground rules

1. **Query the way a person (or a screen reader) finds things**: `getByRole` with an accessible name, `getByLabelText`;
   never a class name, `data-slot` or test id. If a control cannot be found that way, that is a finding about the UI
   (fact 10), not a reason to reach for a selector.
2. **`userEvent`, not `fireEvent`** (fact 7). `const user = userEvent.setup()` per test.
3. **Mock only the framework's edge**: `useRouter` from `next/navigation`. Nothing else is faked: not Base UI, not
   `next/link`, not the date library.
4. **Assert the outcome, whole**: the entire pushed URL, the entire accessible name, and the call count. Use
   `toHaveBeenCalledExactlyOnceWith(url, { scroll: false })`, never `toHaveBeenCalled()` or `toHaveBeenCalledWith` alone: a pick
   that navigated twice would add a history entry and break Back (B3-D8) while every `toHaveBeenCalledWith` stayed green (PR1-3).
5. **Absence is asserted with `queryBy*`** (returns `null`); `getBy*` throws.
6. **No snapshot tests.** They would pin Tailwind class strings, which change every session, and say nothing about what
   they prove.
7. **Expected values come from outside the code under test** (table below), and each test says so.

### Where the expected values come from

| Value | Source |
|---|---|
| 28 rows, 25 shows, `2026-09-28`–`2026-10-25`; 20 dates carry shows | `lib/fixtures/shows.json`, generated from `app/sample_data.py` (the API's default window is today-equivalent plus 27 days); counts re-derived from the file |
| 2026-10-07 is a **Wednesday** → heading `Wed, Oct 7`; five shows on it (ids 8, 22, 23, 24, 25) at four venues (Terminal Bar, White Squirrel ×2, Zhora Darling, Midway) | The calendar; B4's fixture-day table; re-read from `shows.json` |
| `1:00 AM Thu` for show 25 (listed under Wed 10-07) | The after-midnight rule (`requirements-initial.md`, "Times after midnight"); `dates.test.ts` pins the `1:00 AM Sat` form; probed on the real component |
| `9:00 PM – 11:30 PM, show details`, `$18 adv / $22 door`, `Free`, `Time not listed · Details` | Probed on the real `ShowBlock` with fixture shows 2, 25 and 22; the price strings are pinned independently by `show-format.test.ts` |
| Pushed URLs such as `/?venue=1&venue=3&artist=7&month=2026-10` | Written by hand from `buildCalendarHref`'s docstring (fixed key order venue, artist, month; `/` when empty). **Not** produced by calling `buildCalendarHref` |
| Venue and artist names and ids | `lib/fixtures/venues.json` and `artists.json`, mapped to `{ id, name }` (the shape the page passes) |
| Messages ("No matches found.", "Reset filters", "Clear filters") | `requirements-initial.md` ("Calendar": "No matches found" with a way to reset) and the component source |

### 0. `lib/calendar-href.test.ts` (existing file; cases added) — `hasActiveFilters` (node environment)

One `it.each` table: no filters → `false`; a venue alone, an artist alone, a month alone → `true` each (three clauses,
so three rows); all three → `true`. *Proves:* the predicate that decides both "Clear filters" and which empty message
shows. Dropping one clause (M4) silently misroutes a month-only visitor. Source: the three filter kinds in
`CalendarFilters`.

### 1. `app/_components/filter-header.test.tsx` (new, jsdom) — the first named target

*Helpers (written, explained in the file):* `renderHeader(filters)` renders `FilterHeader` with fixture venues and
artists and two months (`2026-10` October 2026, `2026-11` November 2026); `beforeEach(() => push.mockClear())`.
Props mirror what the page passes; the file says so.

**Labels and chips**
1. Venues, Artists and Month each resolve through `getByLabelText`. *Proves:* the `<label htmlFor>` / `id` pairing,
   which is what makes each control announceable.
2. Selected venues render as chips showing **names**, not ids (`venueIds: [1, 3]` → "The White Squirrel Bar", "Zhora
   Darling"). *Proves:* the chip shows a name while the URL carries the id (the component's own comment).
3. The Month trigger shows the current month's label, or "Next four weeks" when there is none. Assert with
   `toHaveTextContent` (substring): the trigger's text also carries the chevron glyph (probed: `"October 2026▼"`).

**Navigation** (every assertion is on `push`)
4. **[K2]** With `venueIds: [3]`, `artistIds: [7]`, `month: "2026-10"` chosen, picking White Squirrel pushes
   `/?venue=1&venue=3&artist=7&month=2026-10` with `{ scroll: false }`. *Proves:* a pick keeps the other filters and
   writes the one canonical URL (ascending ids, fixed key order). Red under M1 and M2.
5. Clicking an already-selected option removes it: `[1, 3]`, click Zhora Darling → `/?venue=1`.
6. The Artists box writes `artist=`, not `venue=`: pick one artist → `/?artist=<id>`. *Proves:* the two pickers are not
   wired to each other's key.
7. Choosing a month pushes `/?month=2026-11`.
8. Choosing "Next four weeks" with a venue and a month set pushes `/?venue=1`. *Proves:* only the month clears, and the
   sentinel value `next-four-weeks` never reaches a URL (M3).
9. **[D3]** The chip's own button, `getByRole("button", { name: "Remove Zhora Darling" })`, pushes `/?venue=1`. Written
   first and watched fail on the unnamed button, then fixed (step 4).

**The lists**
10. The Month list is "Next four weeks" first, then the server's months in the order given.
11. Typing narrows the venue list (`mid` shows "The Midway Saloon" and hides "Zhora Darling"); typing `zzz` shows "No
    matches". *Proves:* the requirement's "multi-select … with ability to type and filter".

**Clear filters** (`it.each`, three rows + one)
12. A venue alone, an artist alone or a month alone each show a link named "Clear filters" with `href="/"`; no filters
    show none. Red under M4 and M8.

### 2. `app/_components/calendar-grid.test.tsx` (new, jsdom) — what the grid does with rows

*Helper:* a small builder for hand-made `CalendarRow[]`, **independent of `groupCalendar`** so a bug in one cannot hide
a bug in the other.
1. One list item per row, in the order given; each heading is a link to `/day/<date>` reading `Wed, Oct 7`.
2. **Today:** the `isToday` row, and only it, has `aria-current="date"` and a "Today" badge
   (`getByRole("listitem", { current: "date" })`, CONFIRMED to work); no row is marked when none is today. Red under M6.
3. A row with no venues shows "Nothing listed" and no venue heading (B3-D2).
4. A venue column is a heading link to `/venue/<id>` with its shows under it, in the order **given**: grouping and
   sorting are `groupCalendar`'s job, and the grid must not re-order or hide anything.
5. Three shows at one venue render three blocks (no cap of two, B3-D7).

### 3. `app/_components/calendar-results.test.tsx` (new, jsdom) — the empty state and the grouping, rendered (D1)

1. **Integration on the fixture.** All 25 fixture shows with `today="2026-10-07"` (inside the window) render 28 rows and
   25 blocks; the Wed Oct 7 row holds 5 blocks under 4 venue headings, one of them the Midway show as `1:00 AM Thu`; exactly
   that row has `aria-current="date"`. *Proves:* the date grouping is wired through to the page: every served date has a
   row, every show is in its own date's row, and the after-midnight show stays under the night it was listed. The counts,
   the heading and the `current` row were run on the prototype; the `1:00 AM Thu` line inside the row is the one assertion
   not yet run there (the block alone was probed). Red under M6 and M7.
2. **Filtered and empty** (a month filter, no shows) → "No matches found." and a link named "Reset filters" with
   `href="/"`, and no list. **[K3]**
3. **Unfiltered and empty** → "No shows listed for these dates.", **no** reset link, **no** "No matches". **[K3]** Fact 14:
   this test is the only check this branch has.
4. Shows present, filters on → neither message.

### 4. `app/_components/show-block.test.tsx` (new, jsdom, D2) — fixture shows 2, 22 and 25

1. A timed show's time line is the link to its page: show 2 → a link named `9:00 PM – 11:30 PM, show details` with
   `href="/show/2"` (the visually hidden suffix is part of the name: B4-D3).
2. An after-midnight show displays the next day: show 25 → `1:00 AM Thu, show details`.
3. Untimed: show 22 with `start_time: null` → "Time not listed", a "Details" link to `/show/22`, and no "show details" link.
4. An end time with no start: "Start time not listed – 11:30 PM".
5. `withVenue`: true → a link "Zhora Darling" to `/venue/3`; false → none.
6. Lineup: each artist links to `/artist/<id>`; show 2 prints `9:00 PM` and `10:30 PM` beside the two acts; a **single** act
   prints no time even when it has one (show 22 with an act `start_time`).
7. Admission: show 2 → `$18 adv / $22 door`; show 25 → `Free`; show 22 → **no price line at all**, and in particular not
   "Free" (`api-contract.md` §4: not stated is not free).

### 5. The pins (new, jsdom, D2)

- `app/error.test.tsx`: the error's message (`connect ECONNREFUSED 10.0.0.5:5432`) is **not** in the output; the digest is
  shown when present (`Reference: abc123`) and no "Reference" line when absent; "Try again" calls `retry` exactly once.
- `app/_components/remote-image.test.tsx`: `javascript:`, `data:`, `file:`, `null`, `undefined` and `""` each render
  **no** `<img>` (the list `httpUrlOrNull` already pins in `detail-format.test.ts`; this proves the component honours
  it); an `https:` URL renders one with the given `alt`, `loading="lazy"`, `decoding="async"` and
  `referrerpolicy="no-referrer"`; a passed `className` is added to the defaults.
- `app/_components/json-ld.test.tsx`: **tests the server's markup, not a client render** (PR1-1). Render with
  `renderToStaticMarkup(<JsonLd data={evil} />)` from `react-dom/server` and parse the result as a document:
  `` new DOMParser().parseFromString(`<!doctype html><body>${html}</body>`, "text/html") ``. For a name containing
  `</script><script>alert(1)</script>` the parsed body must hold exactly **one** `<script type="application/ld+json">`
  whose `JSON.parse(textContent)` equals the original; an array renders as one script. *Proves (and the file says so):*
  `render()` goes through React DOM on the client, which sets the script's text with `innerHTML`, and that path never
  treats `</script>` as an end tag, so a Testing Library render is green even for an unescaped `JSON.stringify`. The
  breakout only happens when the server's HTML goes through the document parser, which is what search engines do. Pairs
  with `json-ld.test.ts`, which pins that the *string* never has a `<`.

### What is *not* covered, stated plainly

- Every `async function Page()`, `layout.tsx` and `CalendarBody` (style guide: Playwright).
- `Updating…`, `aria-busy` and the optimistic chip while a navigation is in flight (fact 12).
- That a real `router.push` re-renders the server page with new data: B5 proves the URL the header *asks for*, not what
  Next does with it. The B3 browser check and, later, Playwright cover it.
- The unfiltered-empty message against a real empty window (fact 14).
- Layout: the sideways scroll, `sticky` headings and the `sr-only` containment bugs (B3-CR1-4, `notes.md`) depend on a
  real layout engine; jsdom has none. These stay a headless-Chrome measurement.
- `WindowNav`, `DetailRow`, `CalendarSkeleton`, `NotFound`: links and static markup; their logic is in tested `lib/` modules.
- The shadcn combobox and select as primitives: only as exercised through the filter header.
- Node 24 (CI) and Ari's laptop: verified on Node 22.22.0 only (Verification 7).

### Tests-first caveat

Two different red states, both to be watched before any fix. **Infrastructure:** the first `calendar-grid.test.tsx` run
fails with `Unexpected JSX expression` (fact 1, already reproduced), and with the JSX setting but no jsdom it fails with
`document is not defined`; each gets fixed in step 1 and the failure is recorded. **Components:** `CalendarResults` and
`hasActiveFilters` do not exist yet, so, as in B2–B4, empty exported stubs that `throw` come first and the assertions
fail rather than the imports.

## Implementation steps

Order: the tooling first (nothing else can run without it), then the one production refactor (captured before and
after), then the test files from the highest-value target down, then the pins, the mutation pass and the docs.

### Working protocol for [fill-in] steps

As in B2–B4 and `AGENTS.md` "[fill-in] tasks": everything around each lesson is written (imports, helpers, fixtures,
every other test, the `Proves:` comments); the few lines that carry a lesson become `TODO(Ari)` blocks with **Lesson /
Code / Check**; each placeholder throws (`throw new Error("TODO(Ari)")`); then stop and hand off with a file:line list.
"Implement B5" does not fill the blocks. Before handoff the three `Code:` snippets are applied in a scratch copy,
everything is run, and the scaffold is restored byte for byte (checksums). Cloud sessions push the scaffold with its
tests red and name them in the PR (`AGENTS.md`, "Branches and PRs", item 5); this milestone is cloud-suited (no model, no
venue sites), and Ari fills the gaps locally.

### TODO(Ari) gaps

Three blocks, **all in test code** (departure 5). **Fill order: K1 first**, because while K1 is open the whole
`filter-header.test.tsx` file fails to load, so K2's test cannot run. K3 is independent. Each lesson sits where the
concept lives, not where the typing is: none of these is a JSX or import line.

- **K1 — Mock the router at the framework's edge, `app/_components/filter-header.test.tsx`** (step 3).
  *Lesson:* `FilterHeader`'s only contact with Next is `useRouter().push` (B3-K4: a pick changes the URL and the server
  re-renders). Outside a running Next app there is no app router, so the unmocked component throws `invariant expected
  app router to be mounted` (fact 8). The test replaces **exactly that edge**, not Base UI and not `next/link`, and
  asserts on what `push` received; because the URL *is* the filter state (`arch-initial.md` §4), the pushed URL is the
  behaviour. `vi.mock` is hoisted above the imports, so anything its factory reads eagerly must come from `vi.hoisted`.
  *Code:*
  ```
  const { push } = vi.hoisted(() => ({ push: vi.fn() }));
  vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
  ```
  *Scaffold shape (PR1-2):* the gap is left as `const { push } = vi.hoisted((): { push: Mock } => { throw new Error("TODO(Ari)"); });`
  with **no** `vi.mock` line (`Mock` imported from `vitest`). The annotation keeps `push` typed for the tests that use it, so
  `pnpm check-types` and `pnpm lint` stay green; Ari replaces the body and adds the `vi.mock` line.
  *Check:* `pnpm --filter calendar test filter-header`. While open, the file does not load: Vitest reports one failed suite,
  `Error: TODO(Ari)`, with **zero tests** run (no individual test fails); filled, all of them run. Likeliest mistakes: a top-level `const push = vi.fn()` read eagerly inside the factory (`Cannot access
  'push' before initialization`), or mocking more than the router (a faked combobox passes while proving nothing about it).
- **K2 — Drive the combobox like a person and assert the whole URL, same file, the first "Navigation" test** (step 3).
  *Lesson:* three habits in four lines. Locate by **role and accessible name**, the way a screen-reader user perceives the
  page. Use **`userEvent`**: a combobox opens on the pointer-and-focus sequence a real click produces, and `fireEvent.click`
  dispatches one bare event after which the list never opens (fact 7). Assert the **entire** pushed URL with the other
  filters preselected, so a component that forgets them, or sorts wrongly, fails; and write the expected string by hand
  from `buildCalendarHref`'s documented key order, **not** by calling `buildCalendarHref`, which would agree with itself
  whatever it did (`AGENTS.md`: tests that read expectations from the code under test can't catch it being wrong).
  *Code:*
  ```
  const user = userEvent.setup();
  renderHeader({ venueIds: [3], artistIds: [7], month: "2026-10" });
  await user.click(screen.getByLabelText("Venues"));
  await user.click(await screen.findByRole("option", { name: "The White Squirrel Bar" }));
  expect(push).toHaveBeenCalledExactlyOnceWith("/?venue=1&venue=3&artist=7&month=2026-10", { scroll: false });
  ```
  *Check:* the test goes green on the real header, and goes **red** when `filter-header.tsx` is mutated by M2 (a venue pick
  drops the other filters) or M1 (`{ scroll: false }` removed): the second is what makes the options argument matter.
  Likeliest mistakes: `fireEvent.click` (times out waiting for the option), the expected URL built with
  `buildCalendarHref`, or `expect(push).toHaveBeenCalled()` with no argument (passes under both mutations). `toHaveBeenCalledWith`
  is a weaker miss: it ignores a second navigation, which `toHaveBeenCalledExactlyOnceWith` catches (PR1-3).
- **K3 — The empty state's second half: assert absence, `calendar-results.test.tsx`** (step 5).
  *Lesson:* the requirement ("No matches found" with a link to reset) has a quieter half: with **nothing** filtered there is
  nothing to reset, so the page must neither say "No matches" nor offer a reset (telling an unfiltered visitor to reset
  their filters). One component, two behaviours, and the bug is the wrong one showing. `getBy*` throws when an element is
  missing, so absence is asserted with `queryBy*`, which returns `null`. And the reset is checked as a real **link with
  `href="/"`**, not text: it is server-rendered and has to work before hydration (the same reasoning as "Clear filters").
  *Code:*
  ```
  // filtered + empty
  expect(screen.getByRole("link", { name: "Reset filters" })).toHaveAttribute("href", "/");
  // unfiltered + empty
  expect(screen.queryByRole("link", { name: "Reset filters" })).not.toBeInTheDocument();
  expect(screen.queryByText(/No matches found/)).not.toBeInTheDocument();
  ```
  *Check:* `pnpm --filter calendar test calendar-results`: green on the real component, **red** under M5 (the reset link
  shown even when nothing is filtered) and M4 (`hasActiveFilters` forgets `month`, so a month-only empty result offers no
  reset). Likeliest mistakes: `getByRole(…)` followed by `.not.…` (throws instead of asserting absence), or asserting the
  message text but not that the way out is a link.

### 1. Tooling (written) — Checked facts 1–5

- `pnpm --filter calendar add -D jsdom@^29 @testing-library/react @testing-library/dom @testing-library/user-event
  @testing-library/jest-dom`. The lockfile changes (~500 lines) and **must be committed**: CI runs
  `pnpm install --frozen-lockfile`. Never edit it by hand.
- `vitest.config.ts` becomes two projects (`extends: true`): `unit` (`environment: "node"`, `include: ["**/*.test.ts"]`) and
  `components` (`environment: "jsdom"`, `include: ["**/*.test.tsx"]`, `setupFiles: ["./test/setup-dom.ts"]`), plus the root
  `oxc: { jsx: { runtime: "automatic" } }`. Keep the `@` and `server-only` aliases and their comments; rewrite the header
  comment, which still says jsdom "arrives in B5". The comment explains that **the extension picks the environment** and why
  JSX needs the setting (fact 1).
- New `test/setup-dom.ts`: `import "@testing-library/jest-dom/vitest"`, then `afterEach(() => cleanup())` (fact 5), each with a
  why-comment.
- *Red first:* write `calendar-grid.test.tsx`'s first test, run it, record `Unexpected JSX expression`; add the JSX setting,
  record `document is not defined`; add the project and setup file, watch it pass. Existing 283 tests stay green and unmodified.

### 2. `hasActiveFilters` and `CalendarResults` (written) — D1

- **Before touching `page.tsx`, capture the baseline** (Verification 4): API up, `next start`, headless Chromium
  `--dump-dom`, `<main>` text for the six URLs, with the sanity counts.
- Tests first (sections 0 and 3 above, the stubs red). Then `hasActiveFilters` in `lib/calendar-href.ts` (keep that file
  import-free), `app/_components/calendar-results.tsx` (a sync component, why-comment: it exists so this branch is
  testable; the page streams around it), `page.tsx` uses it, and `filter-header.tsx:93` calls `hasActiveFilters`.
- Re-capture and compare; must be identical.

### 3. The filter header's tests (fill-in: K1, K2) — `filter-header.test.tsx`

Tests 1–3, 5–8 and 10–12 of section 1 are written complete; test 4 carries K2 and the mock carries K1. Test 9 (the chip's
button) is added in step 4.

### 4. Chip-remove accessible name (written) — D3 (skip if Ari takes the alternative)

Test 9 first, watched fail (`Unable to find an accessible element with the role "button" and name "Remove Zhora Darling"`);
then `removeLabel` on `ComboboxChip` in `packages/ui/src/components/combobox.tsx` (optional prop, `aria-label` on
`ChipRemove`) and `removeLabel={`Remove ${o.name}`}` in `FilterHeader`. If Ari takes the alternative: `it.todo` and a
`notes.md` entry instead.

### 5. Grid and results tests (written, fill-in: K3) — sections 2 and 3

All written complete except the K3 assertions in results tests 2 and 3.

### 6. `ShowBlock` tests (written) — section 4 (D2)

### 7. The pins (written) — section 5 (D2)

### 8. The mutation pass (written) — Verification 3

Run every mutation in the table, record the red test, restore, and show `git diff` is clean afterwards.

### 9. Docs and bookkeeping (written)

- `alpha-build-plan.md`: tick the B5 boxes, record departures 1–5 and D1–D4, keep Playwright deferred.
- `apps/calendar/AGENTS.md`: replace the "jsdom and Testing Library arrive with the first component tests (B5)" bullet with
  how tests work now (extension picks the environment; `userEvent`; mock only `next/navigation`; the `CalendarResults`
  extraction as the pattern: *pull the sync part out of an async page*); add `CalendarResults` and `hasActiveFilters` to the
  file notes.
- `docs/references/nextjs-style-guide.md`, Testing: its "neither app has a test setup yet" sentence has been stale since B1;
  point it at `apps/calendar/AGENTS.md`.
- `docs/dev/conventions.md`: add the `B5` row to the scopes table.
- `docs/dev/notes.md` (real surprises only): Vite 8 + `jsx: preserve` → "Unexpected JSX expression"; the jsdom 30 / Node 22.22.2
  floor; `fireEvent` does not open Base UI's combobox; streamed HTML is not byte-stable and jsdom cannot run `$RC`, so compare
  `<main>` in a real browser; the unnamed chip buttons (if D3 is the alternative).

## Critical files

- New: `apps/calendar/test/setup-dom.ts`; `apps/calendar/app/_components/{calendar-results,calendar-results.test,filter-header.test,
  calendar-grid.test,show-block.test,remote-image.test,json-ld.test}.tsx`; `apps/calendar/app/error.test.tsx`
- Modified: `apps/calendar/vitest.config.ts`, `apps/calendar/package.json`, `pnpm-lock.yaml` (generated by pnpm),
  `apps/calendar/app/page.tsx`, `apps/calendar/app/_components/filter-header.tsx`, `apps/calendar/lib/calendar-href.ts` and its
  `.test.ts`; with D3, `packages/ui/src/components/combobox.tsx`; docs in step 9
- Reused as-is: `lib/{calendar,dates,show-format,detail-format,json-ld}.ts`, `app/_components/{calendar-grid,show-block,
  remote-image,json-ld}.tsx`, `app/error.tsx`, `lib/fixtures/*.json`
- Not touched: `apps/api` (no API or contract change), `lib/api-types.ts`, any fixture

## Verification

1. **Tests first.** The infrastructure red states are recorded (Tests-first caveat); each new test file was run with its
   stubs or missing config and failed for the stated reason before the fix.
2. **`make check` green**, except that at handoff the tests behind the open gaps fail and the log lists exactly which:
   `filter-header.test.tsx` as one failed suite with zero tests run (K1 makes the whole file fail to load), plus the two K3 tests in
   `calendar-results.test.tsx`. Baseline: 14 files / 283 tests; the log records the new totals (roughly fifty tests
   added, about twenty of them D2's). `pnpm lint` and `pnpm check-types` report nothing.
3. **Mutation pass.** Each mutation is applied to the component alone, the suite run, and the named test must go red.
   M1–M8 are CONFIRMED on the prototype (fact 15); M9–M13 are PLAUSIBLE until built.

   | # | Mutation (temporary) | Must go red |
   |---|---|---|
   | M1 | `filter-header.tsx`: `router.push(buildCalendarHref(next))`, `{ scroll: false }` dropped | K2's test, and every other test asserting the options argument |
   | M2 | A venue pick sends `{ venueIds: ids, artistIds: [], month: null }` | K2's test |
   | M3 | The month select sends `value` instead of `null` for "Next four weeks" | header test 8 |
   | M4 | `hasActiveFilters` drops `|| filters.month !== null` | `hasActiveFilters` table; "Clear filters" (a month alone); the filtered-and-empty results test |
   | M5 | `CalendarResults` shows the reset link even when unfiltered | K3's unfiltered test |
   | M6 | `calendar-grid.tsx`: remove `aria-current` | grid test 2; results test 1 |
   | M7 | `CalendarResults` passes `today: null` | results test 1 |
   | M8 | The "Clear filters" link points to `/?x=1` | the three "Clear filters" rows |
   | M9 | `ShowBlock`: `admission ?? "Free"` | show-block test 7 |
   | M10 | `ShowBlock`: per-act times shown on single-act bills | show-block test 6 |
   | M11 | `ErrorPage` renders `error.message` | error test 1 |
   | M12 | `RemoteImage` uses `src` directly, skipping `httpUrlOrNull` | remote-image `javascript:` row |
   | M13 | `JsonLd` uses `JSON.stringify(data)` instead of `jsonLdScriptContent` | the json-ld server-markup `</script>` test (PR1-1: the client-render version stays green, so it is not the one that counts) |

   `git diff` after the pass must show none of them left behind.
4. **The extraction is invisible** (D1; fact 13). Same six URLs, API up (`uv run uvicorn app.main:app` from `apps/api`,
   sample data), `next start`, headless Chromium (`/opt/pw-browsers/chromium-1194/chrome-linux/chrome --headless=new
   --no-sandbox --virtual-time-budget=8000 --dump-dom`); strip `<script>` from `<main>`; before and after must be byte-identical,
   **with the sanity counts printed beside the verdict** (articles 25 / 8 / 1 / 0 / 25 / 23, skeletons 0), so a pair of
   skeletons cannot pass. Stop servers by pid (`ps -eo pid,args | grep "[n]ext-server"`), never `pkill -f` (`notes.md`).
5. **Build and bundle unchanged.** `API_BASE_URL=http://127.0.0.1:9 pnpm build`: succeeds, the same nine routes all `ƒ`.
   `grep -rl "Do not use built-in arithmetic operators with" .next/static` finds nothing (the header now imports
   `hasActiveFilters` from the Temporal-free `calendar-href.ts`), and `grep -rl "testing-library\|jsdom" .next/static` finds nothing.
6. **Tests can run offline and in isolation**: `pnpm --filter calendar test` needs no API, no network, no env file.
7. **Node versions.** Verified on Node 22.22.0 only. CI is Node 24 and Ari's laptop is unknown; neither is verifiable here, so
   the handoff says so and Ari runs `pnpm --filter calendar test` locally.
8. **Ari's check.** The test run (above); with D3, one look at a chip's remove button in the browser's accessibility pane (name
   "Remove …"); and that the filter header looks and behaves as before.

## Not doing in B5

Playwright (deferred in the build plan, and where the async pages, `Updating…`, a real navigation and the unfiltered-empty
window belong); snapshot tests; coverage thresholds; mocking the API (the pure `lib/` layer is tested against fixtures, and
components take props, so no network layer is needed); testing `WindowNav`, `DetailRow`, `CalendarSkeleton`, `NotFound` or any
page; visual regression; any change to the API, its types or the fixtures.

## Follow-ups for other milestones

- **Playwright (the deferred item):** the list under "What is not covered" is its starting backlog: the async pages, the
  real-router flow behind the header, `Updating…`/`aria-busy`, and the empty window.
- **Hosted phase / Dependabot:** a `jsdom` 30 PR needs Node `^22.22.2 || ^24.15.0 || >=26.0.0`; CI's newest-24.x resolution very
  likely satisfies it, a cloud session on 22.22.0 or a laptop on an older 24.x will not (fact 2).
- **Other unlabeled controls:** B5 found one by testing; a second look at the remaining Base UI wrappers (select items, the
  combobox clear) belongs to the first accessibility pass, not here.

## Plan review

### Round 1 — Claude Opus 5.5, October 16, 2026

**Scope:** the plan as committed in `01de543` (no code yet). **Read:** `AGENTS.md` ("[fill-in] tasks", "Implementation
plans"), `apps/calendar/AGENTS.md`, `docs/references/nextjs-style-guide.md` (Testing, Anti-patterns),
`alpha-build-plan.md` §6 B5, `arch-initial.md` §4 libraries table, `requirements-initial.md` ("Calendar" empty state),
`conventions.md` (scope table), the B3 plan's handoff pattern, and the code the plan touches or tests:
`app/page.tsx`, `app/_components/{filter-header,calendar-grid,show-block,remote-image,json-ld}.tsx`, `app/error.tsx`,
`lib/calendar-href.ts`, `packages/ui/src/components/combobox.tsx`, `vitest.config.ts`, `turbo.json`, `Makefile`, CI,
`.github/dependabot.yml`, and `lib/fixtures/{shows,venues,artists}.json`.

**Run, in a throwaway `git worktree` at `4286333` (removed afterwards; the real tree was not touched):**
`pnpm install --frozen-lockfile`, then the plan's five dev dependencies (resolved to jsdom 29.1.1, RTL 16.3.3, dom 10.4.2,
user-event 14.6.8, jest-dom 7.0.1; lockfile +495 lines), the plan's two-project `vitest.config.ts` with the Oxc JSX
setting, and `test/setup-dom.ts`. Results:
- Baseline is **14 files / 283 tests**, all green in the `unit` project beside the jsdom project (facts 4–5). CONFIRMED.
- A prototype `filter-header.test.tsx` with K1 and K2 as written: K2's test, the "Next four weeks" pick (`/?venue=1`),
  the Month trigger's `toHaveTextContent("October 2026")`, typing `mid` / `zzz`, and "Clear filters" with a month alone
  all pass on the real header (facts 6–7). CONFIRMED. With two chips the only two buttons have `aria-label` null and
  empty text (fact 10). CONFIRMED.
- `pnpm check-types` and `pnpm lint` pass with the `.test.tsx` files present (jest-dom's types through the setup file,
  fact 9). CONFIRMED.
- Mutation M12 (`RemoteImage` skips `httpUrlOrNull`): five of the six "no `<img>`" rows go red. CONFIRMED.
- Mutation M13 (`JsonLd` uses `JSON.stringify`): the test **as section 5 describes it stays green**; see #1. CONFIRMED.
- Fixture facts: 28 dates `2026-09-28`–`2026-10-25`, 25 shows on 20 dates; 2026-10-07 holds ids 8, 22, 23, 24, 25 at four
  venues; show 2 is 21:00–23:30 with acts at 21:00 / 22:30 and $18/$22; show 22 has a start time (18:00) and no price, so
  the plan's overrides for tests 3 and 6 are needed and stated; show 25 is 01:00 and free; venue ids 1 White Squirrel,
  2 Midway, 3 Zhora, 4 Terminal; artist 7 is Humbird. All as the plan says. CONFIRMED.
- `npm view jsdom@30 engines` → `^22.22.2 || ^24.15.0 || >=26.0.0`; jsdom 29.1.1 → `^20.19.0 || ^22.13.0 || >=24.0.0`;
  jest-dom 7 → `node >=22`. CONFIRMED.

Not run: Verification 4 (the browser `<main>` comparison) and 5 (`next build`); both need the API and a build, and the
method is sound as written. The test approach is tests-first throughout, and the three gaps sit where the testing
concepts live (the mock at the framework's edge, user-like driving with a whole-URL assertion, asserting absence);
none is markup or imports.

**Counts:** 0 blocker, 1 should-fix, 4 nit. **Verdict: proceed after fixes.**

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | should-fix | **The planned `JsonLd` test cannot catch the bug it is for (M13).** Section 5 renders `<JsonLd>` with Testing Library and checks that `JSON.parse(textContent)` round-trips and that the container holds one `<script>`. `render()` goes through React DOM on the client, which sets the script's content via `innerHTML`, and fragment parsing in a `<script>` context never treats the text `</script>` as an end tag. So the unescaped `JSON.stringify` output also round-trips and also leaves one script. The `</script>` breakout only happens when the **server's HTML** goes through the document parser. A version that does go red: `renderToStaticMarkup(<JsonLd data={evil} />)` from `react-dom/server`, parsed with `` new DOMParser().parseFromString(`<!doctype html><body>${html}</body>`, "text/html") ``, then assert one `<script>` and the `JSON.parse` round-trip. This works in the jsdom project as-is. | CONFIRMED in the worktree: with `JSON.stringify(data)` in place of `jsonLdScriptContent(data)`, the client-render test passed, and the `renderToStaticMarkup` + `DOMParser` test failed with `expected <script …(1)></script><script></script> to have a length of 1 but got 2`. Both pass on the real component. | The pin is green whatever `JsonLd` does, which is the failure `AGENTS.md` warns about ("tests that … can't catch that code being wrong"). The Verification 3 mutation pass would probably expose this during implementation, but the plan's test description and M13's "Must go red" row are written for the version that can't fail. Change section 5's json-ld bullet to the server-markup form and say in its `Proves:` why a client render is not enough. | **Fixed.** Section 5's json-ld bullet now renders with `renderToStaticMarkup` and parses the HTML with `DOMParser`, asserts one script plus the `JSON.parse` round-trip, and states in its `Proves:` why a client render stays green; the M13 row in Verification 3 names that test as the one that must go red. Accepted on the reviewer's reproduction (green client render, red server-markup test under `JSON.stringify`); I did not re-run it, and Verification 3's mutation pass re-confirms it at build time. |
| 2 | nit | **K1's scaffold shape is unspecified, and its Check contradicts Verification 2.** K1's Check says "every test in the file fails with `TODO(Ari)`". Verification 2 says "K1 makes the whole file fail to load". The second is what happens: a throw while the module is being evaluated is reported as `FAIL … [ filter-header.test.tsx ]  Error: TODO(Ari)`, `(0 test)`, under "Failed Suites", and no test fails individually. The plan also doesn't say how the scaffold declares `push`, which every written test uses. Leave it undeclared and `check-types` fails as well, which breaks "`pnpm lint` and `pnpm check-types` report nothing". One shape that keeps both green: `const { push } = vi.hoisted((): { push: Mock } => { throw new Error("TODO(Ari)"); });` with no `vi.mock` line (`Mock` imported from `vitest`). Ari then replaces the body and adds the `vi.mock` line. | CONFIRMED in the worktree: that scaffold gives the load failure above, and `pnpm check-types` and `pnpm lint` both pass with it. | The handoff tells Ari to expect red tests and he sees a red *suite* with zero tests. Or the implementer picks a shape that breaks typecheck, and `make check` at handoff fails for a reason the log doesn't list. State the scaffold shape in K1 and make the two descriptions agree. | **Fixed.** K1 now has a "Scaffold shape" line (`vi.hoisted((): { push: Mock } => { throw … })`, no `vi.mock` line, typed so `check-types` and `lint` stay green), and its Check says the file fails to load as one failed suite with zero tests; Verification 2 says the same. |
| 3 | nit | **`toHaveBeenCalledWith` doesn't check that a pick navigates exactly once.** K2's Code and tests 5–9 use `expect(push).toHaveBeenCalledWith(url, { scroll: false })`, which passes when `push` was called with that URL *among other calls*. Under B3-D8 (`push`, not `replace`, so Back undoes a filter change), a second push per pick would add an extra history entry, and these assertions would not notice. Vitest 5 has `toHaveBeenCalledExactlyOnceWith(url, { scroll: false })`, which checks both the arguments and the count. That is ground rule 4 ("assert the outcome, whole") applied to the call count. | CONFIRMED: the K2 test and the "Next four weeks" test both pass with `toHaveBeenCalledExactlyOnceWith` on the real header (`beforeEach(() => push.mockClear())` already resets the count). | A double navigation per pick (for example a future `onValueChange` + `onInputValueChange` wiring) breaks Back and passes every header test. Cheap to close now, and it fits K2's lesson. | **Fixed.** K2's Code uses `toHaveBeenCalledExactlyOnceWith`, ground rule 4 requires it for every push assertion (the call count is part of "assert the outcome, whole"), and K2's likeliest-mistakes note says why `toHaveBeenCalledWith` alone is a weaker miss. |
| 4 | nit | **The jsdom 30 floor is incomplete.** Fact 2 and the "Hosted phase / Dependabot" follow-up say jsdom 30 needs Node ≥ 22.22.2 and that "CI's Node 24 satisfies it". The actual range is `^22.22.2 \|\| ^24.15.0 \|\| >=26.0.0`, so Node 24 before 24.15 is excluded too. CI's `node-version: 24` resolves to the newest 24.x, so CI is very likely fine, but a laptop on an older 24 is not. | CONFIRMED: `npm view jsdom@30 engines`. CI: `.github/workflows/ci.yml:94`. | The `notes.md` entry and the follow-up would give the wrong floor to whoever hits it on a 24.x laptop. Quote the whole range. | **Fixed.** Fact 2, its consequence cell and the Dependabot follow-up quote `^22.22.2 \|\| ^24.15.0 \|\| >=26.0.0`, and the `notes.md` entry in step 9 will carry the same range. |
| 5 | nit | **"Four dev dependencies" vs five.** The first row of the Context table says "Four dev dependencies". Fact 3, departure 1 and step 1 say five (and five is correct). | Plan, Context table row 1 vs. fact 3 and step 1. | Small inconsistency. It would get copied into the build-plan departure text in step 9. | **Fixed.** The Context table's first row now says "Five dev dependencies". |

**Rejected:** none. All five findings were accepted. #1 rests on the reviewer's reproduction rather than a re-run of mine; Verification 3 (M13) re-checks it when the test is built.

## Implementation log

### Round 1 — Claude Sonnet 5.5, October 16, 2026 (the build)

**Approval:** Ari approved the plan on October 16, 2026 and accepted D1–D4 as recommended (recorded in "Decisions for Ari"). Status went `Awaiting approval` → `Approved` → `Code review`.

**Scope:** the commit range **`b601c5a..HEAD`** on `claude/busy-carson-tyjbix` (the build is the commit after `b601c5a`; the commit is pushed with the tests for the open gaps red, per `AGENTS.md` "Branches and PRs", item 5). Files:
- New: `apps/calendar/test/setup-dom.ts`; `apps/calendar/app/_components/calendar-results.tsx`; tests `app/_components/{calendar-grid,calendar-results,filter-header,show-block,remote-image,json-ld}.test.tsx` and `app/error.test.tsx`.
- Modified: `apps/calendar/vitest.config.ts`, `package.json`, `pnpm-lock.yaml` (generated by `pnpm add`, +497 lines); `app/page.tsx`, `app/_components/filter-header.tsx`; `lib/calendar-href.ts` and `.test.ts`; `packages/ui/src/components/combobox.tsx` (D3).
- Docs: `alpha-build-plan.md` (B5 section), `apps/calendar/AGENTS.md`, `docs/references/nextjs-style-guide.md` (one stale sentence), `docs/dev/conventions.md` (`B5` scope, `<scope>-M<n>` form), `docs/dev/notes.md` (one new entry), this plan (decisions recorded, this log).
- Not touched: `apps/api`, `lib/api-types.ts`, any fixture.

**What was built, by step:** (1) five dev dependencies and a two-project config; (2) `hasActiveFilters` and `CalendarResults` extracted (D1); (3) the filter header's tests, with K1 and K2 scaffolded; (4) the chip-remove accessible name (D3), test first; (5) grid and results tests, K3 scaffolded; (6) `ShowBlock` tests; (7) the three pins; (8) the mutation pass; (9) docs.

**Tests-first record.** Infrastructure: with the old config the first `calendar-grid.test.tsx` run failed with `Unexpected JSX expression`; after the Oxc setting alone, with `document is not defined` in all 7 tests; after the two projects and the setup file, it passed and the 283 existing tests stayed green and unmodified. `hasActiveFilters` and `CalendarResults` were throwing stubs first (9 red, `not implemented`) and then implemented. D3: with K1/K2 filled in scratch, exactly one test failed, `Unable to find an accessible element with the role "button" and name "Remove Zhora Darling"`, the other 14 passed, and the 3-line fix turned it green.

**Departures from the plan, each with its reason:**
1. **Verification 5's second bundle grep is narrowed.** The plan's `grep -rl "testing-library\|jsdom" .next/static` hits one chunk, but the match is Base UI's own runtime check (`/jsdom|happydom/.test(userAgent)`), already shipped before B5. Checked: `testing-library` and `user-event` have **0** hits. The recorded check is `testing-library|user-event`; the `jsdom` note is in `notes.md`.
2. **The json-ld test asserts the `type` with `getAttribute`, not `toHaveAttribute`.** Elements of a `DOMParser` document have no `defaultView`, and jest-dom rejects them ("received value must be an HTMLElement"). Commented in the file and in `notes.md`.
3. **Mutation labels are scoped in code (`B5-M4`) and the `M` form is registered** in `docs/dev/conventions.md` (`<scope>-M<n>`), because the repo's rule is that code and tests always scope designations. The plan itself still writes them bare, as the defining document.
4. **`include` globs are by extension** (`**/*.test.ts` node, `**/*.test.tsx` jsdom), not by directory as in my first prototype. `exclude` is repeated per project because `extends: true` doesn't merge it.
5. **Test counts differ from the plan's estimates.** Filter header: 15 tests (the plan listed 12 items; the `it.each` is 3 cases and the chip test was added). Totals below.
6. **A small import reformat.** `filter-header.tsx`'s `@/lib/calendar-href` import was reformatted from its odd multi-line shape while adding `hasActiveFilters`; no other line of that import changed meaning.

**`TODO(Ari)` gaps (all open, none filled):**
- **K1**, the router mock: `apps/calendar/app/_components/filter-header.test.tsx:36` (placeholder at `:53`). Lesson: mock exactly the framework edge (`useRouter`) with `vi.hoisted`; the pushed URL is the behaviour.
- **K2**, drive the combobox and assert the whole URL: `app/_components/filter-header.test.tsx:128` (placeholder at `:149`). Lesson: role/name queries, `userEvent` not `fireEvent`, one exact `push` with the other filters preserved, expected URL written by hand.
- **K3**, the empty state's two halves: `app/_components/calendar-results.test.tsx:118` (`:130`) and `:151` (`:163`). Lesson: the reset must be a real link to `/`, and absence is asserted with `queryBy*`.
- Command: `pnpm --filter calendar test filter-header calendar-results`. **Fill K1 first**; while it is open the filter-header file fails to load (one failed suite, zero tests).
- Handoff state is exactly that: K1 = 1 failed suite, K3 = 2 failed tests, everything else green.

**Verification (commands run, results):**
- Scaffold state, `make check`: ruff clean; mypy `no issues found in 31 source files`; eslint (`--max-warnings 0`) and `next typegen && tsc` clean in all packages; **pytest 669 passed, 15 skipped**; Vitest **21 files, 321 tests visible: 319 passed, 2 failed (K3), plus `filter-header.test.tsx` (15 tests) not loading (K1)**. Make stops at the first failing target, so `make contract-check` was run on its own: `Generated contract output is current.`
- **Snippets applied in a scratch copy** (K1, K2 and K3's `Code:` lines in place): **21 files, 336 tests, all passing**; `pnpm check-types` and `pnpm lint` clean. The scaffold was then restored and checked against checksums taken before the fill (identical), and `git status` shows no `*.orig` or stray files. (A later whitespace-only fix to the K2 block's indentation changed the file's checksum; the filled snippet is unaffected.)
- **Mutation pass, M1–M13, all RED**, each caught by the test the plan names, with the files restored afterwards: M1 6 tests, M2 1, M3 1, M4 3, M5 1, M6 2, M7 1, M8 3, M9 1, M10 1, M11 1, M12 4 (the empty-string and the three scheme rows; `null` and `undefined` still render nothing under that mutation, as expected), M13 2 (the server-markup test; the client-render version the plan rejected was not re-run).
- **D1 equivalence (Verification 4), in headless Chromium against `next start` with the API up:** `<main>` of `/`, `/?venue=1`, `/?venue=2&artist=7`, `/?month=2027-01`, `/?venue=abc`, `/?month=2026-10` **byte-identical before and after**, with sanity counts articles 25 / 8 / 1 / 0 / 25 / 23 and skeletons 0 in both. The baseline was captured on the unmodified tree before `page.tsx` was touched; I confirmed the rebuilt `.next` postdates the edit and references the new component.
- **Build (Verification 5):** `API_BASE_URL=http://127.0.0.1:9 pnpm build` succeeds; the same nine routes, all `ƒ`; `grep -rl "Do not use built-in arithmetic operators with" .next/static` finds nothing.
- Baseline for comparison: 14 files / 283 tests; with the work: 21 files / 336 tests when the gaps are filled (53 added, of which D2's `ShowBlock` + pins are 22).

**Not verified:** Node 24 (CI) and Ari's laptop (this sandbox is Node 22.22.0); the D3 name in a real screen reader or the browser's accessibility pane (that is Ari's check, Verification 8); that a Dependabot jsdom 30 bump behaves as `notes.md` predicts.

**Where to look hardest:**
1. **K1's scaffold shape** (`vi.hoisted((): { push: Mock } => { throw … })`): written so `check-types` and `lint` stay green; confirm it reads clearly for Ari.
2. **The D3 change lives in a shared package** (`packages/ui/src/components/combobox.tsx`, 7 lines including a comment). `aria-label={removeLabel}` is `undefined` when no label is passed, so other callers are unchanged; confirm nothing else uses `ComboboxChip`.
3. **`CalendarResults`'s props** (`start`, `end`, `shows`, `today`, `filters`): it takes `filters` and derives "filtered" itself, rather than a boolean, so the page can't pass a stale one.
4. **The `components` project's setup** (`vitest.config.ts`): `extends: true` carrying `resolve.alias` and `oxc` into both projects, and the extension-based `include`.
5. **The json-ld test's reliance on `DOMParser`** and `renderToStaticMarkup`: it is the one test whose value depends on a subtle fact (client render stays green under the bug).
6. **Whether any test would still pass under a mutation I did not think of**; the pass covered the 13 in the plan.
