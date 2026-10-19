# B6 — accessibility and end-to-end tests

**Status:** Plan review
**Date:** October 19, 2026
**Author model:** Claude Sonnet 5.5
**Reviewer model:** (set by the plan-review round)
**Spec:** `docs/dev/alpha-build-plan.md` §6 B6 (scope agreed with Ari October 17, 2026; the milestone text was written by Haiku and is scrutinised below), `docs/arch/requirements-initial.md` Global Requirements ("Accessibility: WCAG 2.2 Level AA"), `docs/arch/arch-initial.md` §4 (the two-layer enforcement paragraph, and the libraries table), `docs/references/nextjs-style-guide.md` ("Testing": async Server Components and full flows go to Playwright), `apps/calendar/AGENTS.md`, `AGENTS.md` ("Conventions": *Tests state what they prove*; "[fill-in] tasks"; "Cloud sessions"), `docs/dev/implementations/b5-frontend-testing.md` (its "What is *not* covered" and "Follow-ups" are B6's inbox), `docs/dev/notes.md` ("The home page's window moves with the clock…")

## Context

B5 unit-tested every piece of the frontend that Vitest and jsdom can reach (337 tests now) and deferred what they can't: the async Server Components, a real router, `aria-busy`, streaming, layout. B6 adds the tool that can see those things (Playwright driving a real Chromium against the real app), and uses it for a second job the requirements added on October 17: **WCAG 2.2 Level AA** for every screen, checked by an automated scan inside the same suite plus a manual keyboard and screen-reader pass.

What B6 is *not*: a browser matrix beyond Chromium, visual snapshots, API or agent tests (pytest), any change to the API contract, dark mode (it does not exist, see S3), or the fixes themselves until Ari has marked the findings (the process, D9).

### What B6 delivers

| Piece | What |
|---|---|
| A harness | `apps/calendar/e2e/`, a Playwright config that starts the whole stack (real FastAPI on the sample data, a delay proxy, `next start` on a production build), `make e2e`, a CI job |
| Journeys | 11 journeys (J1–J9, with J6 in three parts), one story per test, in a real browser: home, filter, no-match, Back, day-view sorting, venue/artist/show pages by link, 404s, the busy state, the skeleton |
| An accessibility scan | axe with the WCAG 2.2 AA tags on **every screen** and on the popup states, against a **ratchet baseline** (D5), plus three checks axe cannot make: reflow, focus not obscured, painted focus-indicator contrast |
| A findings table | What the scan and the checks found, with a proposed severity, for Ari to mark; the fix round follows his marks |
| A manual-pass script | What Ari does with a keyboard and a screen reader, and how it is recorded |

## Scrutiny of the milestone as written

The build-plan text for B6 was checked against the code and against a running prototype (next section). It is mostly sound: one test green first, then the scan, then the journeys, one at a time, is the right order and this plan keeps it. These are the places it is wrong, incomplete or underspecified.

| # | In the build plan | Actual | Consequence for this plan |
|---|---|---|---|
| S1 | "Standing rule: the test clock": the default home window is "today plus 27 days", so the real clock empties the page after October 25; "Known date cliff": the home page thins out from October 26. `notes.md` says the same | **Wrong for today's code.** `shows.py` sets `start = data.START`, a pinned constant, so the window is **Sep 28 – Oct 25 whatever the date is** (the page's own comment says so). The only code that reads the real clock is `metroToday()` in the Next server, which decides **which row says "Today"** (fact 7). Nothing empties on October 26. The rule's *mechanism* line is also incomplete: `page.clock` is browser-side and cannot reach a Server Component | The pin is still needed, but for the Today row (and, later, for the API when A1b makes its clock real, see Follow-ups). The rule and the `notes.md` section are rewritten (Departure 1). The pin is a `Date.now` preload on the Next server (D2), with an automated guard in place of a memo |
| S2 | Step 1: "real API with a seeded database, or a stub serving `lib/fixtures`" | The first option does not exist yet: the routers still serve `sample_data.py` (A1b is open) and the seed script writes four venues and no shows. A stub of `lib/fixtures` would be a second implementation of the API's filters, ranges, `upcoming`, 404s and 422s. The option the plan omits is the one that works: **the real FastAPI app on `sample_data.py`**, which needs no database (fact 3) | D1 |
| S3 | Step 4: "Axe in dark mode" | **There is no dark mode to scan.** `globals.css` carries shadcn's `.dark` palette, but nothing ever puts the class on `<html>` (no theme provider, no media query), and emulating `prefers-color-scheme: dark` changes nothing (fact 6). The requirements never ask for one | D7: drop it |
| S4 | Journey 3: the empty state "which B5 found unreachable from sample data" | B5 found the **unfiltered** empty message ("No shows listed for these dates") unreachable. The **filtered** one ("No matches found") is reachable through the combobox: Midway + Charlie Parr has no shows (re-derived from `shows.json`) | J3 tests the reachable branch; the unfiltered one stays Vitest-only (B5-K3) and is listed under Not doing |
| S5 | Journey 2 lists `aria-busy` and the optimistic chip as things only a browser shows | True, but with a fast API they last a few milliseconds, so a test would race. They are observable only with a **slowed API**, the same mechanism journey 7 needs. The build plan treats the two as independent | The delay proxy is part of the harness (S1 of this plan's steps), and the busy state is its own journey (J8) |
| S6 | Journey 5: venue, artist and show pages "reached through links" as one row | One test with three destinations breaks the plan's own "one test each" rule and fails with a vague message | Split into J6a, J6b, J6c |
| S7 | Journey 7: "the Suspense skeleton is replaced by content" | The skeleton is `aria-hidden` with no text, so a role-based query cannot find it (the project's rule, B5) and a screen reader hears nothing while the page loads (fact 9) | D8 |
| S8 | Step 2: the scan runs "on the same page", the home page | The requirement is "every screen". Of the 5 URLs with a finding, 4 are not the home page (fact 4). And static scans miss states: `aria-hidden-focus` appears **only while the combobox popup is open**, on none of the 16 URLs at rest (fact 5) | Step 5: every screen, at two widths, plus the popup states and the error screen |
| S9 | Step 2: "report-only at first … once clean, the build fails on a new violation" | "Report-only" cannot enforce anything and "once clean" waits on fixes Ari has not yet marked. There are real violations today (fact 4) | D5: a ratchet baseline that fails on anything new from the first commit, and makes each fix a red→green test |
| S10 | Step 2: "measure the two colour values that were hand-calculated and not rendered: the focus ring on white, and muted text on muted backgrounds" | axe's `color-contrast` rule covers text only; **no axe rule measures the focus indicator or a control's border** (WCAG 1.4.11). Measured by diffing focused against unfocused screenshots: the painted ring is **1.54:1** on links (fact 8). The muted-on-muted pair is 4.35:1 by arithmetic (below 4.5), but no rendered text uses it: the chip is `text-foreground` on `bg-muted`, and the skeleton has no text | Step 6 adds the measurement as a test whose result goes through the same ratchet; the muted pair is recorded as "not rendered" |
| S11 | Step 4: "A keyboard-only journey through the filter header and a show block" | The requirement names **visible focus "not covered by sticky headers"** (WCAG 2.4.11, new in 2.2), and the calendar has sticky date headings. Nothing in the plan checks for coverage, and Playwright's `toBeVisible()` ignores overlap | K2 |
| S12 | Step 4: "Reflow at 320px and 375px: no page-level horizontal scroll" | Sound, but it quietly relies on a position the plan never states: the venue rows scroll sideways **on purpose** (requirements: "horizontally scrolling row of venue columns"). WCAG 1.4.10 allows two-dimensional content as an exception; whether this layout qualifies is a judgement | D6, K3. Prototype: no route scrolls the page sideways at 320 or 375 |
| S13 | Nothing on how `incomplete` axe results are handled | axe returns a third bucket for what it could not decide. Two venue links at 375px came back "partially obscured by another element" (fact 4) | Policy in S3 below: recorded and triaged by hand, not failed |
| S14 | Nothing on CI, `make check`, `.gitignore`, `turbo.json` | Each needs a decision or a change: the CI job design is the plan's own stated open question; `make check` claims to mirror CI; ESLint (`--max-warnings 0`) rejects undeclared env vars in `playwright.config.ts` (fact 11); `playwright-report/` and `test-results/` are not ignored | D4, steps 1 and 7 |
| S15 | "Steps 1–5 below" | There are six steps; and Step 1 says "nothing else is added until it is green" while the item above it adds `@axe-core/playwright` in the same step | Axe lands in this plan's Step 3. "Three runs in a row … in CI" is read as one CI job run with `--repeat-each=3` on Step 1's commit, because a CI "run" is a push |
| S16 | Step 5/6: findings "Ari marks", fixed "before the step closes" | `/build-milestone` runs unattended and stops at sign-off, so a mid-step mark cannot happen inside one run | D9: two implementation rounds, which `AGENTS.md` already allows |
| S17 | `arch-initial.md` §4 libraries table: Playwright is "already a dependency for the agent pipeline's headless fetch" | That is the **Python** package (`playwright>=1.62.0` in `apps/api/pyproject.toml`). The JS runner is a separate, new dependency in `apps/calendar` | Departure 9 (one row) |

## Checked before planning

Everything below was run in a **throwaway `git worktree`** (`pnpm install --frozen-lockfile`, then `@playwright/test` and `@axe-core/playwright` added there only), against the real FastAPI app and a production `next build`/`next start`, on this sandbox's Node 22.22.0. The worktree and every probe were deleted afterwards; **no probe is in the repo**, so the build re-derives each number rather than trusting this table. CONFIRMED means run and read.

| # | Fact | Evidence | Consequence |
|---|---|---|---|
| 1 | **Versions.** `@playwright/test` 1.64.1 and `@axe-core/playwright` 4.14.0 (axe-core 4.14.0), the latest on npm today; `@axe-core/playwright` peers `playwright-core >= 1.0.0`. `pnpm install` added them in seconds and **downloaded no browser** | CONFIRMED (`npm view`, `pnpm add`). Next has an optional peer on `@playwright/test`, so the lockfile's `next@16.3.0(…)` key gains a `(@playwright/test@1.64.1)` suffix: cosmetic churn | Dependencies approved October 17 |
| 2 | **The sandbox cannot download Playwright's browser** (`playwright install chromium` → "Download failure"). It has an older preinstalled Chromium (`/opt/pw-browsers/chromium`, build 1194; Playwright 1.64.1 wants 1248). **That older build ran every probe correctly** | CONFIRMED | `launchOptions.executablePath` from an env var, `E2E_CHROMIUM_PATH`. CI and laptops use `playwright install --with-deps chromium` (PLAUSIBLE: not verifiable here) |
| 3 | **The real API serves the sample data with no database running.** `uvicorn app.main:app` with a dummy `DATABASE_URL` answers `/shows`, `/metro` and the rest; nothing connects | CONFIRMED | D1. The e2e job needs `uv` and Node, not Postgres |
| 4 | **The axe baseline** (tags `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa`; 16 URLs at 1280, 375 and 320 wide): **one rule fires, `target-size` (serious, WCAG 2.5.8)**: artist links in show blocks are `<a class="underline">` **18px high** (needs 24). On `/` (6 nodes), `/day/2026-10-07` and `?sort=time` (2 each), `/artist/1` (2), `/day/2026-10-20` (2); the same at every width. Everything else is clean, including both 404 pages. At 375 and 320, `/` also returns **two `color-contrast` results as `incomplete`** ("background … partially obscured by another element": the Zhora Darling and The Terminal Bar venue links) | CONFIRMED | Findings F1 and F4 below. S13's policy |
| 5 | **A state the static scan misses.** With the Venues combobox popup open, axe reports **`aria-hidden-focus` (serious, 5 nodes)**: Base UI marks `<header>`, `<footer>` and others `aria-hidden` (they carry `data-base-ui-inert`) while they still contain focusable elements. With the Month popup open, only `target-size` | CONFIRMED that it fires; root cause (library behaviour, a prop, or a false positive) **not investigated** | F2. Step 5 scans open popups |
| 6 | **No dark mode.** The `<html>` class is `font-sans …` with and without `prefers-color-scheme: dark` emulation (background stays white). Adding `.dark` by script applies the palette, and that scan is clean, but it is a state no user can reach | CONFIRMED | D7 |
| 7 | **The clock.** The Today row (`aria-current="date"`) is **Mon, Oct 19** today (the real date). The "Showing" range is the pinned Sep 28 – Oct 25. Preloading `Date.now = () => FROZEN` into the Next server with `NODE_OPTIONS=--import` moves the row to **Wed, Oct 7**, with no production-code change. **Subclassing `Date` instead crashes the app** (`TypeError: Date.UTC is not a function` while the Temporal polyfill loads) | CONFIRMED | D2; the gotcha goes in `notes.md` |
| 8 | **Painted focus indicators**, measured as the pixels that change between an unfocused and a focused screenshot of the same clip: artist link, nav link and day-heading link all change white → rgb(208,208,208) = **1.54:1**; the Month select's border goes 229 → 181 = **1.63:1**. (The prototype focused the wrong element for the Venues combobox, so its ring is unmeasured.) `--ring` itself is 2.58:1 on white, but the app paints the link outlines at 50% alpha (computed `outline-color` is the ring colour at 0.5). Unfocused control borders (`--input`, 229) are **1.26:1** on white. `--muted-foreground` on `--muted` is 4.35:1; on the background, 4.74:1 | CONFIRMED (two earlier methods, edge-band sampling and computed styles, disagreed and were abandoned: text and underline pixels contaminate the first, and the second reads the unpainted token) | F3, F6. Method for Step 6. WCAG 1.4.11 asks 3:1 of the visual information that identifies a focused control: CONFIRMED the numbers, **PLAUSIBLE** that this is how Ari reads the criterion, so the severity is his call |
| 9 | **Skeleton and streaming.** The skeleton (`CalendarSkeleton`) is `aria-hidden="true"` with no text. A delay proxy between Next and the API (`POST /__delay/1500`) makes the shell paint at ~0.3–0.7 s, the skeleton stay for the delay, then articles replace it: **3 of 3 repeats** passed. A browser-side `page.route` cannot do this: the fetch happens on the Next server | CONFIRMED | D8; the delay proxy |
| 10 | **Reflow and focus.** No page-level horizontal scroll at 320 or 375 on any of the 16 URLs (`scrollWidth == clientWidth`). Tabbing 159 stops on `/`: at 1280, no stop's centre is covered; at 375, no centre is covered but **9 stops have a corner under a sticky heading** (WCAG 2.4.11 AA asks only that the control not be *entirely* hidden, so this passes; the AAA sibling would not) | CONFIRMED (the prototype's predicate also accepted `top.contains(el)`; the stricter form K2 uses was **not** run) | K2, K3 |
| 11 | **Tooling fits, with two wrinkles.** Vitest ignores `e2e/*.spec.ts` (its include is `**/*.test.ts`; 337 tests still pass with the folder present). `tsc` and ESLint do cover `e2e/` (tsconfig `include: **/*.ts`; strict indexing applies). **ESLint with `--max-warnings 0` fails** on `process.env.E2E_*` in `playwright.config.ts` (`turbo/no-undeclared-env-vars`). `.gitignore` has no `playwright-report` or `test-results` | CONFIRMED | Step 1 declares the variables in `turbo.json` and ignores the output folders. Pure helpers placed in `e2e/support/*.test.ts` run in `pnpm test` with no browser (K1) |
| 12 | **Cost.** `next build` 26 s here. The 16-URL axe sweep took ~26–28 s per width, ~1.7 s a page, mostly `networkidle` waits | CONFIRMED | Suite estimate ~2–3 min plus the build: PLAUSIBLE until measured. The every-screen scan runs at 1280 and 375, reflow only at 320 |
| 13 | **Selectors for the journeys.** `<article>` per show block (25 on `/`); the filter controls are labelled `Venues`, `Artists`, `Month`; the day view's three sort links are `By venue` / `By time` / `By artist`, the current one `aria-current="page"`; `role="status"` holds "Updating…"; the 404 heading is "Not found" with a link "Back to the calendar" | CONFIRMED by reading `filter-header.tsx`, `day/[date]/page.tsx`, `not-found.tsx` | Every locator is role- and name-based (the B5 rule) except the skeleton, until D8 |

### Findings the prototype already has (the baseline's first rows)

These are the content of the findings table the build records, with a **proposed** severity (Ari marks them, D9). IDs are `B6-F<n>`.

| ID | Finding | WCAG | Found by | Proposed |
|---|---|---|---|---|
| F1 | Artist links in show blocks and day/artist lists are 18px high | 2.5.8 AA | axe `target-size` | must-fix: an AA failure, and `/day/[date]` already solved it (`inline-block py-1`) |
| F2 | `aria-hidden-focus` while a combobox popup is open | 4.1.2 A | axe, popup state | should-fix until the cause is known: may be upstream |
| F3 | Focus indicator is 1.54:1 (links) and 1.63:1 (Month select); Venues combobox unmeasured | 1.4.11 AA | Step 6 measurement | must-fix if Ari reads 1.4.11 as covering focus rings (the W3C Understanding document does) |
| F4 | Two venue links' contrast undecidable at ≤375px ("partially obscured") | 1.4.3 AA | axe `incomplete` | to triage by eye |
| F5 | The skeleton is silent: no status text while the calendar loads | 4.1.3 AA (judgement) | by reading, S7 | should-fix; D8 |
| F6 | Unfocused control borders are 1.26:1 on white | 1.4.11 AA | Step 6 measurement | should-fix or nit: depends on whether the label alone identifies the field |

Not findings, recorded so nobody re-checks them: reflow at 320/375 passes everywhere; focus is never entirely hidden; both 404 pages are clean; `bypass`, `document-title`, `html-has-lang`, `label`, `link-name` and `button-name` pass on every screen.

## Departures from the build plan (to apply to `alpha-build-plan.md` when implementing)

1. **Rewrite the "Standing rule: the test clock" and "Known date cliff" paragraphs** (S1), and the `notes.md` section of the same name: the API window is pinned; the Next server's `metroToday` is the one clock; the rule is "one constant, guarded by a unit test"; the cliff arrives with A1b.
2. Step 1 includes the `make e2e` target, the CI job, `.gitignore`, `turbo.json`. `@axe-core/playwright` is installed in Step 3, not Step 1 (S15). "Three runs" is `--repeat-each=3`.
3. Step 1's stack option is **the real API on `sample_data.py`** (S2, D1).
4. **Dark mode is dropped** from Step 4 (S3, D7).
5. The journey table is corrected and extended (S4–S7): J3's note, J6 split in three, the busy state (J8) and the skeleton (J9) share a delay proxy, a Back-button journey (J4) is added (B3-D8: push, not replace, is what makes Back undo a filter; jsdom cannot show history).
6. Step 2's "report-only" becomes a **ratchet baseline** (S9, D5); Step 5 gains every-screen and popup-state scans (S8); Step 4 gains the focus-not-obscured check (S11) and the painted-focus measurement (S10); `incomplete` results get a policy (S13).
7. Step 5 ("Run, review, resolve") becomes a **second implementation round** after Ari's marks (S16, D9).
8. Marking: Steps 1, 2, 4, 5 and 7 [written]; three `TODO(Ari)` gaps (K1–K3) in Steps 3 and 6 [fill-in] (D10).
9. Docs: `arch-initial.md` §4 libraries row (S17); `nextjs-style-guide.md` Testing paragraph ("Playwright is still deferred"); `apps/calendar/AGENTS.md` (an E2E section: stack, ports, the clock, the proxy, `E2E_CHROMIUM_PATH`); root `AGENTS.md` "Cloud sessions" (e2e runs there, with `E2E_CHROMIUM_PATH=/opt/pw-browsers/chromium`); `conventions.md` scope table (a `B6` row); `notes.md` (the clock section rewritten; the `Date`-subclass gotcha; `pkill -f` is already there).

## Decisions for the user / reviewer

Each has a recommendation and the alternative on record. **Ari: D1, D2, D4, D5, D6 and D9 change what gets built or how it is run; the rest are low-stakes.**

- **D1 — The stack the tests run against. Recommended: the real FastAPI app serving `sample_data.py`** (S2, fact 3), started by Playwright's `webServer` on dedicated ports (API 8101, proxy 8102, Next 3100, so a running `make dev` is never reused and never collides). *Alternatives:* a stub serving `lib/fixtures` (the fixtures are response bodies, not the logic that picks them, so the stub would re-implement the filters, ranges, `upcoming`, 404s and 422s, and could drift); or wait for A1b and use a seeded Postgres (blocks B6 on another milestone, and the seed has no shows). *Consequence of the recommendation:* when A1b swaps the routers onto the database, the e2e job gains a Postgres service and a deterministic show seed; A1b already has an open item about keeping a sample-data source (build plan A1b, last bullet), and this strengthens it (Follow-ups).
- **D2 — How the clock is pinned. Recommended: a test-only `--import` preload on the Next server that patches `Date.now`** (fact 7), the pin held as one constant (`2026-10-07T17:00:00Z`, noon Wednesday in Minneapolis, inside the sample window with five shows on it) and **guarded by a Vitest test** that fails when the pin leaves the fixtures' window or its date has no show. *Alternatives:* an env override read by the app (a production hook that exists only for tests); or no pin and no assertion on the Today row (loses the only browser-level check of `aria-current="date"`). Note the guard replaces the build plan's "move the pin in the same change" memo with a red test.
- **D3 — Production build or dev server. Recommended: `next build && next start`.** It is what visitors get (streaming, no development overlay). *Alternative:* `next dev`: no build step, but Next's dev tooling injects its own elements into every page, which would put findings in the scan that no visitor sees (PLAUSIBLE; not measured). Cost: a 26 s build before each run.
- **D4 — CI and `make check`. Recommended:** a separate `e2e` job in `ci.yml` (Node 24, `uv sync --locked`, `playwright install --with-deps chromium`, a cache for the browser, the report uploaded on failure), and `make e2e` added to `make check` so "everything CI runs" stays true. *Alternatives:* fold it into the `js` job (slower feedback for every JS change; needs Python there); or leave `make check` without it and say so in the Makefile header (`check` then no longer mirrors CI). The branch has no protection yet (`env-setup.md`), so "the build fails" means a red job.
- **D5 — Report-only or ratchet. Recommended: a ratchet baseline** (K1, S9). *Alternative:* report-only until the findings are fixed (nothing fails until a later change flips a switch, so a new violation can land in the meantime).
- **D6 — Reflow and the sideways-scrolling rows. Recommended:** treat each venue row's own scroll region as WCAG 1.4.10's two-dimensional-content exception, assert only that the **page** never scrolls sideways (K3), and rely on axe's `scrollable-region-focusable` plus the keyboard pass to confirm each scroller is reachable. *Alternative:* stack the venue columns vertically below 320px (a layout change to the B3 design, which is Ari's). Ari's call because it is a reading of a criterion about his own design.
- **D7 — Dark mode. Recommended: drop it from B6** (S3). Add it to the scan matrix if the app ever gets a theme switch. *Alternative:* scan a forced `.dark` page anyway: it is clean today and describes a state that does not ship.
- **D8 — The skeleton's handle. Recommended: a visually hidden `role="status"` paragraph "Loading shows" beside the decorative bars** (which stay `aria-hidden`). It gives a role-based test its locator and gives screen-reader users a loading state (F5), the same shape as B5-D3 (a defect found while writing tests, fixed with a test first). It touches `calendar-skeleton.tsx` and its message. *Alternatives:* a `data-testid` (breaks the project's "role, name or label only" rule and leaves F5); a class selector on `animate-pulse` (brittle, same).
- **D9 — Process around findings. Recommended: two implementation rounds.** Round 1 builds Steps 1–7, records the findings table with proposed severities, passes code review, and stops at `Awaiting sign-off` with the **marking request first in the handoff**. Ari marks F-items; round 2 (Step 8) fixes the marked ones, each in its own commit, test first, then sign-off. This uses `AGENTS.md`'s existing "second implementation pass gets its own log round", and honours the build plan's "Ari marks, then fixed" without a mid-run stop. *Alternatives:* the build run fixes everything it proposes as must-fix without waiting (WCAG AA is already a stated requirement, so the decision could be treated as made, but the build plan says Ari marks); or a mid-build stop after Step 3 (changes the cycle's gates).
- **D10 — Marking. Recommended: K1–K3 [fill-in]; everything else [written].** K1 (the ratchet comparison) and K2 (the focus-obscured predicate) are the lessons about *what the check means*. K3 (the reflow predicate) is the weakest (two lines); if Ari wants fewer gaps, drop K3 and keep it [written]. *Alternative:* all [written], which `AGENTS.md` allows when no line carries a lesson; this plan thinks two do.

## WCAG 2.2 AA coverage matrix

How each criterion that applies to this app is checked. **Automated checks are a floor** (`arch-initial.md` §4). "axe" means the scan with tags `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa`; "custom" means a check B6 writes because axe has no rule; "manual" means Ari's pass.

| Criterion | Level | How it is checked |
|---|---|---|
| 1.1.1 Non-text content | A | axe (`image-alt`); manual: is each alt text meaningful (venue photo "Photo of …", poster alt) |
| 1.3.1 Info and relationships | A | axe (lists, definition lists, labels); manual: heading outline (h1, a date h2 per row, venue headings) |
| 1.4.1 Use of colour | A | axe `link-in-text-block`; links are underlined; manual |
| 1.4.3 Contrast (minimum) | AA | axe `color-contrast` on rendered pairs, every screen, popup states; **incomplete** results triaged by hand (F4) |
| 1.4.4 Resize text | AA | manual (200% browser zoom); the 320px reflow run covers 400% |
| 1.4.10 Reflow | AA | custom, K3, 320 and 375px on every route; the row scrollers are the stated exception (D6) |
| 1.4.11 Non-text contrast | AA | custom: painted focus indicators and unfocused control borders, ratcheted (F3, F6); axe has no rule |
| 1.4.12 Text spacing | AA | manual (text-spacing override, then look) |
| 1.4.13 Content on hover or focus | AA | manual (the combobox and select popups: dismissible with Esc, not lost on pointer move) |
| 2.1.1 Keyboard | A | custom keyboard journey (filters, popups, a show block by Tab/Enter/arrows); axe `scrollable-region-focusable`; manual |
| 2.1.2 No keyboard trap | A | keyboard journey: Esc closes a popup and Tab leaves it; manual |
| 2.4.1 Bypass blocks | A | axe `bypass` (landmarks; there is no skip link); manual: is that enough in practice |
| 2.4.2 Page titled | A | axe `document-title` plus an exact title assertion per route (Step 5) |
| 2.4.3 Focus order | A | keyboard journey logs the order; manual reads it |
| 2.4.4 Link purpose | A | axe `link-name`; the "…, show details" suffixes (B4-D3); manual in a screen reader's link list |
| 2.4.5 Multiple ways | AA | by inspection: nav lists (/venues, /artists), filters, links |
| 2.4.6 Headings and labels | AA | manual |
| 2.4.7 Focus visible | AA | custom (a visible change exists; its contrast is 1.4.11) |
| 2.4.11 Focus not obscured (minimum) | AA, new in 2.2 | custom, K2: Tab through every stop at 1280 and 375, centre point not covered |
| 2.5.7 Dragging movements | AA | N/A: nothing needs dragging (the rows scroll natively) |
| 2.5.8 Target size (minimum) | AA, new in 2.2 | axe `target-size` (it is in the `wcag22aa` tag): F1 |
| 3.1.1 Language of page | A | axe `html-has-lang` |
| 3.2.2 On input | A | **manual judgement**: picking a filter navigates and re-renders without a submit button; is that a change of context that needs advance notice? The Updating… status helps (4.1.3) |
| 3.2.3 / 3.2.4 Consistent navigation / identification | AA | by inspection (one root layout) |
| 3.3.2 Labels or instructions | A | axe `label`; the filters are the only inputs |
| 4.1.2 Name, role, value | A | axe (`aria-*`, `button-name`, `aria-hidden-focus`): F2; the chip-remove names (B5-D3) are asserted in J2 |
| 4.1.3 Status messages | AA | J8 asserts the status region's text appears and clears; **whether a screen reader announces it, and "No matches found", is manual**; F5 |
| N/A for this app | — | 1.3.4 and 1.3.5 (no orientation lock, no personal-data fields), 2.1.4 (no character shortcuts), 2.2.x (no time limits), 2.3.1, 2.5.1–2.5.4, 3.2.1, 3.2.6 (no help mechanism), 3.3.1, 3.3.7, 3.3.8 (no authentication), 1.2.x (no media) |

## Design of the harness

### Layout (all under `apps/calendar/`)

```
playwright.config.ts            one project (chromium, desktop), workers 1, retries 0, webServer ×3
e2e/
  support/
    stack.ts                    ports, URLs, the control client for the proxy
    clock.ts                    the one pinned instant (D2)
    clock.test.ts               Vitest: the pin lies inside the fixtures' window and on a day with a show
    fake-now.mjs                the preload: Date.now only
    delay-proxy.mjs             pass-through proxy: POST /__delay/<ms>, /__fail, /__reset
    test.ts                     `test` extended with a fixture that resets the proxy after every test
    a11y.ts                     AXE_TAGS, scanPage(): axe result → Finding[]
    a11y-baseline.ts            compareToBaseline() (K1) and the committed BASELINE
    a11y-baseline.test.ts       Vitest: the comparison, with hand-made findings
    focus.ts                    isFocusObscured() (K2); focusIndicatorContrast() (screenshot diff)
    reflow.ts                   expectNoPageReflow() (K3)
  home.spec.ts … (one file per journey, below)
```

Specs are `*.spec.ts` (Playwright's `testMatch`); unit tests of the helpers are `*.test.ts` (Vitest's `unit` project picks them up, so they run in `pnpm test` with no browser and in `make check`). Naming keeps the two runners from collecting each other's files (fact 11).

### The stack

Started by Playwright's `webServer` array, in this order, with `reuseExistingServer: false` (a running dev stack has different data and a real clock):

1. **API:** `uv run uvicorn app.main:app --port 8101` in `apps/api`, with dummy `DATABASE_URL` and `MODEL_NAME` (`Settings()` needs them at import; nothing connects, fact 3). Ready when `/health` answers.
2. **Delay proxy:** `node e2e/support/delay-proxy.mjs`, listening on 8102 and forwarding to 8101, adding the delay a test sets (a ~15-line `node:http` file; the prototype's was exactly that). `POST /__delay/<ms>`, `POST /__fail` (answer 502 to everything), `POST /__reset`. **Global state**, which is why `workers: 1` and `fullyParallel: false`, and why the `test.ts` fixture resets it after every test, pass or fail.
3. **Next:** `pnpm exec next start -p 3100` with `API_BASE_URL=http://127.0.0.1:8102`, `NODE_OPTIONS=--import <abs>/e2e/support/fake-now.mjs` and the pinned instant. `NODE_OPTIONS` is set in this one process's `env`, so the Playwright runner itself is not frozen. It needs a prior `next build`; the config fails early with a plain message if `.next/BUILD_ID` is missing. `make e2e` and the CI job build first.

The preload is three lines, and the shape matters (fact 7):

```js
// Test-only. Freeze the Next server's clock. Patch Date.now ONLY: subclassing Date crashes the
// Temporal polyfill at import (Date.UTC is not a function).
const FROZEN = Date.parse(process.env.E2E_FROZEN_NOW);
Date.now = () => FROZEN;
```

Browser: `launchOptions.executablePath` from `E2E_CHROMIUM_PATH` when set (fact 2). Reporter `list` locally; `list` plus `html` (`open: "never"`) in CI; `trace: "retain-on-failure"`. **No retries**: a retry that turns a flaky red into green hides exactly what the "three green runs" rule is for. Teardown: `gracefulShutdown` is set on each `webServer`; the build **verifies no listener remains** on 8101, 8102 or 3100 after a run (PLAUSIBLE that Playwright reaps `uv run`'s child; not exercised here, because the prototype started servers by hand).

`turbo.json` declares `E2E_CHROMIUM_PATH`, `E2E_FROZEN_NOW` and `E2E_BASE_URL` (or the config reads them behind a documented `eslint-disable-next-line`; the build picks whichever makes `pnpm lint` pass with zero warnings, fact 11). `.gitignore` gains `playwright-report/` and `test-results/`.

### The ratchet (D5)

A **finding** is `{ page, ruleId, nodes }`: one entry per page per rule, however many elements. axe results become findings (`ruleId` = the axe rule); the custom checks (reflow, focus-indicator contrast) emit findings of their own (`ruleId: "b6-focus-indicator-3to1"`, `nodes` = how many of a fixed list of focus targets fall below 3:1), so one baseline governs both. `BASELINE` is committed data, each entry carrying the `B6-F<n>` it belongs to. `expectBaseline(page, name)` fails when the page has an **added** finding (not in the baseline, or with more nodes) **or a stale one** (in the baseline but gone, or with fewer nodes). Stale-fails-too is the point: deleting an entry is the red step of a fix, and a fixed rule cannot quietly come back. `incomplete` results are attached to the test report and logged, not failed (S13), and triaged by hand in the log.

## Test approach (written first, watched fail, then made green)

For a browser test "red first" means one of three things, and each step says which: the stack isn't wired (the first test), the expectation is wrong until the pin or the feature exists (the Today row; the skeleton's status), or a deliberate break proves the test can fail (the mutation table, Verification 4).

**Ground rules** (carried from B5, plus three): (1) locate by role, accessible name or label, never a class, `data-slot` or test id; (2) assert the whole outcome (the full URL, the exact heading, the exact count); (3) expected values are written literally in the test with their source in a comment and are never read from the code or the fixtures under test (B5's reasoning: a test that reads its expectation from what it checks cannot catch it being wrong); (4) one journey, one test, one story; (5) every test opens with a `Proves:` comment; (6) no snapshot tests; (7) no `waitForTimeout`: wait on a condition.

### Where the expected values come from

| Value | Source |
|---|---|
| 25 shows on `/`, window Sep 28 – Oct 25 | `apps/api/app/sample_data.py` (26 rows, one deliberately outside the window), the API's pinned window; the same 25 B5 counted in `shows.json` |
| Wed, Oct 7 holds five shows at four venues; show 25 is "1:00 AM Thu" | B5's table, re-read from `shows.json` (ids 8, 22, 23, 24, 25) |
| Venue ids 1 White Squirrel, 2 Midway, 3 Zhora Darling, 4 Terminal Bar; Charlie Parr (artist 1) plays venues 1 and 3 only | `venues.json`, `artists.json`, `shows.json`, re-derived for this plan: Midway + Charlie Parr is a no-match pair |
| Show 2: Zhora Darling, Sep 30, 9:00 PM, link name "9:00 PM – 11:30 PM, show details" | B5's `ShowBlock` table |
| Page titles, 404 text, link and heading names | the components as they stand; the title template is `%s · Agentic Live Music Calendar` (`layout.tsx`) |
| Contrast numbers | fact 8; the build re-measures and writes the measured values in the log |

### Unit tests (Vitest, no browser; written first)

- **`e2e/support/clock.test.ts`:** the pinned instant, converted to `America/Chicago`, falls on a date inside `[start, end]` of `lib/fixtures/shows.json`, and at least one show has that date. *Proves:* the rule the build plan wrote as a memo, as a red test, the day `sample_data.py`'s `START` moves and the fixtures regenerate. The fixtures are the right source here: they echo the API's window, which is what the pin must sit inside.
- **`e2e/support/a11y-baseline.test.ts` (K1):** equal sets → nothing added, nothing stale; a rule absent from the baseline → added; more nodes → added; an entry the page no longer has → stale; fewer nodes → stale; two pages with the same rule are independent. *Proves:* "fails on a new violation" and "a fix is a red→green step" are true and cannot be traded for each other. Expected values are hand-made findings.

### Browser tests (each opens with `Proves:`; selectors per fact 13)

| # | File and journey | Proves | Needs |
|---|---|---|---|
| J1 | `home.spec.ts`: `/` shows "Live music" and the calendar, and the Today row is the pinned date | Step 1: the page loads end to end; with the pin: `aria-current="date"` is on "Wed, Oct 7 Today" and that row holds five articles (the 25 total is asserted too). Red without the pin (today it is Mon, Oct 19) | stack; pin (Step 2) |
| J2 | `filter-venue.spec.ts`: pick "The White Squirrel Bar" in Venues | the URL becomes exactly `/?venue=1`; a chip and a button named "Remove The White Squirrel Bar" appear; only that venue's shows remain (8 of the 25, B5 fact 13); the real router, streaming and optimistic chip work together (B5 backlog) | stack |
| J3 | `filter-empty.spec.ts`: Midway + Charlie Parr | "No matches found." and a link "Reset filters" to `/`; following it restores all 25 shows (the filtered-empty branch B5 could not reach end to end, S4) | stack |
| J4 | `filter-history.spec.ts`: pick a venue, then Back | the URL returns to `/`, the chip is gone and 25 shows are back (B3-D8: `push`, not `replace`; the one history behaviour jsdom cannot see). Not in the build plan; added | stack |
| J5 | `day-view.spec.ts`: `/day/2026-10-07`, then By time, By artist, By venue | each link's URL (`?sort=time`, `?sort=artist`, the bare URL); `aria-current="page"` moves; the first and last rows in each order (written out); the default has one URL (B4-D6) | stack |
| J6a | `venue-page.spec.ts`: from `/`, click the "Zhora Darling" heading link | `/venue/3`, h1 "Zhora Darling", its shows listed | stack |
| J6b | `artist-page.spec.ts`: from `/`, click an artist link ("Beasthead") | `/artist/9`, h1 "Beasthead", its upcoming shows | stack |
| J6c | `show-page.spec.ts`: from `/`, click show 2's time link | `/show/2`, the lineup and time shown, and a page title that names the show (the exact text is read off the page when the test is written and then pinned, B4-D7) | stack |
| J7 | `not-found.spec.ts`: one generated test per URL (`/venue/9999`, `/venue/abc`, `/day/2026-02-30`, `/nope`) | HTTP **404** (not a soft 200) with h1 "Not found" and a link back (B2: `notFound()` must throw). Valid only while detail routes are not behind a streaming boundary (B2-D4 note) | stack |
| J8 | `filter-busy.spec.ts`: delay 1500 ms, pick a venue | `aria-busy="true"` and the status text "Updating…" appear, then clear when the page settles; the chip shows at once (the optimistic value) and stays (B5 fact 12, finally observable) | proxy; delay |
| J9 | `skeleton.spec.ts`: delay 1500 ms, load `/` | the shell and heading are visible first, the "Loading shows" status is present and no article exists; then the articles appear and the status is gone (B3-D4; red until D8's markup exists) | proxy; D8 |

The scans (Step 3 and 5), reflow and keyboard checks (Step 6) are described in the steps.

### What is *not* covered, stated plainly

- Any other browser, any phone or tablet **device** (a narrow viewport is not a phone: touch, the on-screen keyboard and the real scroll feel are the manual pass).
- Whether a screen reader says anything sensible (the matrix's manual rows).
- The unfiltered empty message ("No shows listed for these dates"): no sample window is empty (B5 fact 14); it stays covered by B5-K3 in Vitest.
- The API-down experience beyond the one error-screen scan; the detail routes' bare 500 (a known B2 behaviour) is not a screen to scan.
- Hover and pressed states (the scan sees the DOM at rest and in the states the tests reach).
- A second, slower run of axe in other languages or zoom levels.

## TODO(Ari) gaps

Three blocks, all in test-support code. **Fill order: K1 first** (the baseline every scan depends on), then K2 and K3 (independent). Each is a few lines.

- **K1 — `compareToBaseline` in `e2e/support/a11y-baseline.ts`** (Step 3, [fill-in]).
  *Lesson:* "report-only first, then fail on a new violation" (build plan B6 Step 2) is a ratchet. The baseline lists the known findings as `{ page, ruleId, nodes }` and the scan must **match it exactly**: more than the baseline is *added* (red), less is *stale* (red until the entry is deleted). Without the stale half, fixing one violation silently makes room for a new one of the same rule; without the node counts, a rule can grow from 2 elements to 20 unnoticed. `expect(violations).toEqual([])` would be red on day one, and `length <= n` is the mistake that lets a fix mask a regression.
  *Code:*
  ```ts
  const key = (e: Finding) => `${e.ruleId}@${e.page}`;
  const known = new Map(baseline.map((e) => [key(e), e.nodes]));
  const seen = new Map(found.map((e) => [key(e), e.nodes]));
  return {
    added: [...seen].filter(([k, n]) => (known.get(k) ?? 0) < n), // new, or more elements than known
    stale: [...known].filter(([k, n]) => (seen.get(k) ?? 0) < n), // fixed, or fewer elements than known
  };
  ```
  *Check:* `pnpm --filter calendar test` (`a11y-baseline.test.ts`, red until filled). Likeliest mistakes: comparing rule ids only; checking only `found ⊆ baseline`.
- **K2 — `isFocusObscured` in `e2e/support/focus.ts`** (Step 6, [fill-in]).
  *Lesson:* WCAG 2.4.11 (Focus Not Obscured, minimum, new in 2.2): a focused control must not be **entirely** hidden by author-created content, here the sticky date headings (requirements: "not covered by sticky headers"). Playwright's `toBeVisible()` and `toBeInViewport()` ignore overlap, so ask the browser what is on top **at the control's centre**. Read it after the Tab keypress has resolved, which is after the browser has scrolled the control into view.
  *Code:* `return page.evaluate(() => { const el = document.activeElement as HTMLElement; const r = el.getBoundingClientRect(); const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !(top && (top === el || el.contains(top))); });`
  *Check:* `keyboard.spec.ts` "no Tab stop is covered by a sticky heading" is red until filled (the placeholder throws) and green on the real page at 1280 and 375; mutation B6-M6 (a fixed bar over the top of the page) turns it red. Likeliest mistake: `toBeVisible()`; also accepting `top.contains(el)` (a covering ancestor passes). The prototype used a looser three-clause predicate; this stricter one is unverified until the build runs it.
- **K3 — `expectNoPageReflow` in `e2e/support/reflow.ts`** (Step 6, [fill-in]; the weakest gap, see D10).
  *Lesson:* WCAG 1.4.10 (Reflow): at 320 CSS px wide the **page** must not need a horizontal scrollbar. The venue rows scroll sideways on purpose inside their own regions (D6), so measure the **document**, not `body` (which `overflow-x: hidden` would hide) and not the scrollers. Set the viewport before navigating, so the layout is computed at that width.
  *Code:* `const { w, c } = await page.evaluate(() => ({ w: document.documentElement.scrollWidth, c: document.documentElement.clientWidth })); expect(w).toBeLessThanOrEqual(c);`
  *Check:* `reflow.spec.ts` (320 and 375, every route) red until filled, green on the real pages (prototype: equal everywhere); mutation B6-M5 (a `min-w-[400px]` element in the header) turns it red. Likeliest mistake: measuring `document.body.scrollWidth`.

## Implementation steps

Order matters: tests first, one green thing at a time, and the full suite run at the end of each step (the build plan's rule). Each step ends green before the next starts. **[written]** / **[fill-in]** per Departure 8.

### Step 1 [written] — the harness and one green test
1. Write `home.spec.ts` (J1's first half: `/` shows "Live music" and at least one article) and the config **first**: watch it fail because the stack isn't wired.
2. `pnpm --filter calendar add -D @playwright/test`; `playwright.config.ts`; `e2e/support/stack.ts`, `delay-proxy.mjs` (pass-through only for now), `test.ts`; `turbo.json` env, `.gitignore`.
3. `make e2e` (build, then `playwright test`; `.PHONY`; one comment saying what it starts and why on other ports); the `e2e` job in `ci.yml` (D4), carrying `--repeat-each=3` for this commit; `check:` gains `e2e`.
4. **Done when** `E2E_CHROMIUM_PATH=… make e2e E2E_ARGS="--repeat-each=3"` is green here (the target passes `$(E2E_ARGS)` to `playwright test`), no listener remains on 8101/8102/3100, and the CI job is green with the same flag.

### Step 2 [written] — the clock pin
`clock.ts`, `clock.test.ts` (red first: no pin), `fake-now.mjs`; wire it into the Next `webServer` env; extend J1 to the Today-row assertion (red against the real clock, green with the pin). Remove `--repeat-each=3` from CI.

### Step 3 [written, K1 fill-in] — axe on the home page, with the baseline
1. `pnpm --filter calendar add -D @axe-core/playwright`.
2. `a11y-baseline.test.ts` first (red), then `compareToBaseline` as a scaffold with K1, then `a11y.ts`: `AXE_TAGS` as one constant, `scanPage` turning an axe result into findings and attaching the raw result to the report.
3. `a11y-home.spec.ts`: scan `/` at 1280 against the baseline. The first run is red with F1 as "added"; commit the baseline entry (`B6-F1`, `nodes: 6`) with its finding ID.
4. The two hand-calculated colour values are measured in Step 6; the muted pair is recorded "not rendered" in the log now.

### Step 4 [written] — the journeys, one at a time
J2, J3, J4, J5, J6a, J6b, J6c, J7 (generated), each written red, made green, and followed by a full-suite run. J8 and J9 wait for the proxy's delay mode and D8. The proxy gains `__delay`, `__fail` and `__reset` here, with the `test.ts` reset fixture.

### Step 5 [written] — every screen, and the states
1. **D8:** `calendar-skeleton.tsx` gets the status paragraph, test first (J9 red), and its Vitest component test if the project's rule wants one (a sync component with real markup: yes).
2. J8 and J9 green through the proxy.
3. `a11y-screens.spec.ts`: a generated test per screen in the matrix below, at 1280 and 375, each against the baseline; plus an exact `<title>` assertion per route (2.4.2). New baseline rows: F1 on its pages.

   | Screens | URL |
   |---|---|
   | Home, plain and filtered, and no-match | `/`, `/?venue=1`, `/?venue=2&artist=1` |
   | Day view, three orders | `/day/2026-10-07`, `?sort=time`, `?sort=artist` |
   | Venue, venues list | `/venue/1`, `/venues` |
   | Artist, artists list | `/artist/1`, `/artists` |
   | Show, timed and untimed | `/show/2`, `/show/22` |
   | Diagnostics | `/health` |
   | 404 | `/nope` |
   | Error screen | `/` with the proxy in `__fail` mode (the shell and the error boundary after hydration: PLAUSIBLE from `apps/calendar/AGENTS.md`; confirm at build) |
4. `a11y-popups.spec.ts`: the Venues popup open, the Artists popup open with one option highlighted by keyboard, the Month popup open (fact 5): F2's baseline row.
5. `incomplete` results are written to the log as a table (page, rule, element, reason) for triage (F4).

### Step 6 [written, K2 and K3 fill-in] — layout, keyboard, painted focus
1. `reflow.spec.ts`: every route at 320 and 375 with `expectNoPageReflow` (K3 scaffold, red until filled).
2. `keyboard.spec.ts`: Tab through the home page from the top at 1280 and 375, reading `isFocusObscured` after each stop (K2 scaffold) and logging the visited order; then the filter header by keyboard only (open Venues with the keyboard, pick with Enter, Esc closes and focus returns, the Month select by keyboard) and a show block's link by Enter. This is 2.1.1, 2.1.2 and 2.4.3's evidence.
3. `focus-indicator.spec.ts`: for a fixed list of targets (an artist link, a nav link, a day-heading link, the Venues combobox, the Month select, "Clear filters" on a filtered page), measure the painted indicator by **diffing a focused against an unfocused screenshot of the same clip** (fact 8), and report the unfocused control border too. Targets below 3:1 become a custom finding (`b6-focus-indicator-3to1`, F3) and the borders another (`b6-control-border-3to1`, F6), both in the baseline. The measured values are written into the log. The Venues combobox's first measurement is taken here, on the right element.

### Step 7 [written] — docs, mutation pass, handoff
Departure 1–9's docs; the mutation table (Verification 4) run and recorded; the **findings table** (F1–F6 and anything Step 5–6 added, with measured values, proposed severity and the proposed fix in one line each); the manual-pass script (Verification 7) ready for Ari. Then `make check`, the Implementation log round, and Status `Code review`.

### Step 8 [written] — the fix round (a second implementation round, after Ari's marks, D9)
For each finding Ari marks must-fix or should-fix: delete its baseline row (the red test), fix, green, **its own commit**. Findings marked nit or left unmarked are logged and keep their baseline row. F1's fix is one class change (`inline-block py-1`, the day view's pattern, B4); F3/F6 touch shared tokens or `packages/ui`; F2's cause has to be found first.

## Critical files

| File | Why |
|---|---|
| `apps/calendar/playwright.config.ts`, `e2e/**` (new) | the whole milestone |
| `apps/calendar/package.json`, `pnpm-lock.yaml` | two dev dependencies |
| `Makefile`, `.github/workflows/ci.yml`, `turbo.json`, `.gitignore` | `make e2e`, the CI job, env declarations, ignored output |
| `apps/calendar/app/_components/calendar-skeleton.tsx` (+ test) | D8 |
| `apps/calendar/app/_components/show-block.tsx`, `app/day/[date]/page.tsx`, `packages/ui/src/components/{combobox,select}.tsx`, `app/globals.css` | where the Step 8 fixes would land (F1–F3, F6), only if marked |
| `apps/api/app/routers/shows.py`, `app/sample_data.py` | read-only: the pinned window the plan relies on; not edited |
| `docs/dev/alpha-build-plan.md`, `docs/dev/notes.md`, `docs/arch/arch-initial.md`, `docs/references/nextjs-style-guide.md`, `apps/calendar/AGENTS.md`, `AGENTS.md`, `docs/dev/conventions.md` | Departure 1 and 9 |

## Verification

1. **Unit tests, offline:** `pnpm --filter calendar test`: needs no browser, API or network. `a11y-baseline.test.ts` red until K1 is filled; `clock.test.ts` green.
2. **The suite:** `E2E_CHROMIUM_PATH=/opt/pw-browsers/chromium make e2e` here (cloud); plain `make e2e` on a laptop after `pnpm exec playwright install chromium`. Then the same with `E2E_ARGS="--repeat-each=3"`: green. K2 and K3's tests stay red until Ari fills the gaps; **every other test is green**.
3. **No orphans:** after a run, `ss -ltn | grep -E ':(8101|8102|3100)'` is empty. Stop any stray server by PID, never `pkill -f` (`notes.md`).
4. **Mutations** (each: break one thing, run the named test, see red, restore). The conventions' `M` form; the table is recorded in the log.

   | M | Break | Must go red |
   |---|---|---|
   | B6-M1 | the filter pushes with `replace` instead of `push` | J4 |
   | B6-M2 | the venue page returns "not found" markup instead of calling `notFound()` | J7 (`/venue/9999`) |
   | B6-M3 | remove the `<Suspense>` around `CalendarBody` | J9 |
   | B6-M4 | remove `aria-current` from the Today row | J1 |
   | B6-M5 | a `min-w-[400px]` element in the header | reflow (K3) |
   | B6-M6 | a fixed bar (`fixed inset-x-0 top-0 h-24 bg-background z-50`) in the layout | focus obscured (K2) |
   | B6-M7 | an unlabelled `<button>` on the home page | the home scan (a new `button-name`: "added") |
   | B6-M8 | delete a baseline row (F1) | the scan ("added": the red step of a fix) |
   | B6-M9 | start Next without the pin | J1 |
   | B6-M10 | the chip-remove button loses its `aria-label` | J2 |

5. **`make check`** green apart from K2 and K3's tests (open gaps), with `e2e` included. The CI job green on the PR is **not verifiable from a cloud session** before the push: the handoff says so.
6. **Not verified here:** Node 24 (CI) and Ari's laptop (this sandbox is Node 22.22.0); `playwright install --with-deps chromium` on the CI runner; the browser build Playwright expects (the sandbox ran an older one, fact 2).
7. **Ari's manual pass** (about 45 minutes; recorded in the Implementation log as a table: screen, tool, what happened, finding ID).
   - *Keyboard only, no mouse, Chrome:* `/` from the address bar: Tab through the header and the filters; open Venues with the keyboard, pick one with Enter, remove the chip with the keyboard, Esc, Tab out; the Month select by keyboard; reach a show's time link and press Enter; Back. Note any trap, any moment you cannot see where focus is, any control you cannot reach.
   - *Screen reader (VoiceOver on macOS or NVDA on Windows), on `/`, `/day/2026-10-07`, `/venue/3`, `/artist/9`, `/show/2`, a 404:* the landmarks and heading list; the links list (does "9:00 PM – 11:30 PM, show details" make sense out of context?); each show block's read-out; the filters' announcements ("Venues, combobox …", the chips' "Remove …" buttons); whether **Updating…** is announced after a pick, whether **No matches found** is announced, what is read while the page is loading (F5); whether picking a filter without a submit button is surprising (3.2.2).
   - *Zoom and spacing:* 200% browser zoom on `/`; apply a text-spacing override and look for clipped or overlapping text (1.4.4, 1.4.12).
8. **Ari's gate:** mark each of F1–F6 (and anything new) must-fix, should-fix or nit before round 2.

## Not doing in B6

Visual snapshots; Firefox, WebKit or a device matrix; dark mode (D7); the unfiltered empty message (B5-K3 owns it); API-down journeys beyond the one scan; load or speed tests; scanning `apps/admin` (no role, `arch-initial.md` §7); fixing any finding before Ari marks it (D9); any change to the API, `schemas.py`, the fixtures or `lib/api-types.ts`.

## Follow-ups for other milestones

- **A1b:** the e2e stack depends on a deterministic data source. When the routers move onto Postgres, the e2e job needs a Postgres service **and** a seed that loads the same shows (A1b's open "keep a sample-data source" item now has this consumer). And the API's clock becomes real then: the pin must reach it (a Python-side clock the tests can fix), and the **real date cliff the build plan feared arrives at that point**, not now (S1).
- **H milestones:** the hosted phase may want the same suite against a deployed preview; the harness takes `E2E_BASE_URL`-style configuration but B6 builds for the local stack only.
- **Dark mode:** if it is ever added, add it to the scan matrix.
- **Other unlabelled controls:** B5's follow-up (the remaining Base UI wrappers) is covered by the scan and the popup-state scans.
- **Throttled and offline states, API-down detail pages:** not built; the proxy's `__fail` mode makes them cheap when wanted.
