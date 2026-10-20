# B6 — accessibility and end-to-end tests

**Status:** Awaiting sign-off (code review round 1 resolved; Ari's findings gate, the three `TODO(Ari)` gaps and the manual pass remain)
**Date:** October 19, 2026
**Author model:** Claude Sonnet 5.5
**Reviewer model:** Claude Opus 5.5 (plan review round 1; code review round 1)
**Spec:** `docs/dev/alpha-build-plan.md` §6 B6 (scope agreed with Ari October 17, 2026; the milestone text was written by Haiku and is scrutinised below), `docs/arch/requirements-initial.md` Global Requirements ("Accessibility: WCAG 2.2 Level AA"), `docs/arch/arch-initial.md` §4 (the two-layer enforcement paragraph, and the libraries table), `docs/references/nextjs-style-guide.md` ("Testing": async Server Components and full flows go to Playwright), `apps/calendar/AGENTS.md`, `AGENTS.md` ("Conventions": *Tests state what they prove*; "[fill-in] tasks"; "Cloud sessions"), `docs/dev/implementations/b5-frontend-testing.md` (its "What is *not* covered" and "Follow-ups" are B6's inbox), `docs/dev/notes.md` ("The home page's window moves with the clock…")

## Context

B5 unit-tested every piece of the frontend that Vitest and jsdom can reach (337 tests now) and deferred what they can't: the async Server Components, a real router, `aria-busy`, streaming, layout. B6 adds the tool that can see those things (Playwright driving a real Chromium against the real app), and uses it for a second job the requirements added on October 17: **WCAG 2.2 Level AA** for every screen, checked by an automated scan inside the same suite plus a manual keyboard and screen-reader pass.

What B6 is *not*: a browser matrix beyond Chromium, visual snapshots, API or agent tests (pytest), any change to the API contract, dark mode (it does not exist, see P3), or the fixes themselves until Ari has marked the findings (the process, D9).

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
| P1 | "Standing rule: the test clock": the default home window is "today plus 27 days", so the real clock empties the page after October 25; "Known date cliff": the home page thins out from October 26. `notes.md` says the same | **Wrong for today's code.** `shows.py` sets `start = data.START`, a pinned constant, so the window is **Sep 28 – Oct 25 whatever the date is** (the page's own comment says so). The only code that reads the real clock is `metroToday()` in the Next server, which decides **which row says "Today"** (fact 7). Nothing empties on October 26. The rule's *mechanism* line is also incomplete: `page.clock` is browser-side and cannot reach a Server Component | The pin is still needed, but for the Today row (and, later, for the API when A1b makes its clock real, see Follow-ups). The rule and the `notes.md` section are rewritten (Departure 1). The pin is a `Date.now` preload on the Next server (D2), with an automated guard in place of a memo |
| P2 | Step 1: "real API with a seeded database, or a stub serving `lib/fixtures`" | The first option does not exist yet: the routers still serve `sample_data.py` (A1b is open) and the seed script writes four venues and no shows. A stub of `lib/fixtures` would be a second implementation of the API's filters, ranges, `upcoming`, 404s and 422s. The option the plan omits is the one that works: **the real FastAPI app on `sample_data.py`**, which needs no database (fact 3) | D1 |
| P3 | Step 4: "Axe in dark mode" | **There is no dark mode to scan.** `globals.css` carries shadcn's `.dark` palette, but nothing ever puts the class on `<html>` (no theme provider, no media query), and emulating `prefers-color-scheme: dark` changes nothing (fact 6). The requirements never ask for one | D7: drop it |
| P4 | Journey 3: the empty state "which B5 found unreachable from sample data" | B5 found the **unfiltered** empty message ("No shows listed for these dates") unreachable. The **filtered** one ("No matches found") is reachable through the combobox: Midway + Charlie Parr has no shows (re-derived from `shows.json`) | J3 tests the reachable branch; the unfiltered one stays Vitest-only (B5-K3) and is listed under Not doing |
| P5 | Journey 2 lists `aria-busy` and the optimistic chip as things only a browser shows | True, but with a fast API they last a few milliseconds, so a test would race. They are observable only with a **slowed API**, the same mechanism journey 7 needs. The build plan treats the two as independent | The delay proxy is part of the harness (Step 1 of this plan), and the busy state is its own journey (J8) |
| P6 | Journey 5: venue, artist and show pages "reached through links" as one row | One test with three destinations breaks the plan's own "one test each" rule and fails with a vague message | Split into J6a, J6b, J6c |
| P7 | Journey 7: "the Suspense skeleton is replaced by content" | The skeleton is `aria-hidden` with no text, so a role-based query cannot find it (the project's rule, B5) and a screen reader hears nothing while the page loads (fact 9) | D8 |
| P8 | Step 2: the scan runs "on the same page", the home page | The requirement is "every screen". Of the 5 URLs with a finding, 4 are not the home page (fact 4). And static scans miss states: `aria-hidden-focus` appears **only while the combobox popup is open**, on none of the 16 URLs at rest (fact 5) | Step 5: every screen, at two widths, plus the popup states and the error screen |
| P9 | Step 2: "report-only at first … once clean, the build fails on a new violation" | "Report-only" cannot enforce anything and "once clean" waits on fixes Ari has not yet marked. There are real violations today (fact 4) | D5: a ratchet baseline that fails on anything new from the first commit, and makes each fix a red→green test |
| P10 | Step 2: "measure the two colour values that were hand-calculated and not rendered: the focus ring on white, and muted text on muted backgrounds" | axe's `color-contrast` rule covers text only; **no axe rule measures the focus indicator or a control's border** (WCAG 1.4.11). Measured by diffing focused against unfocused screenshots: the painted ring is **1.54:1** on links (fact 8). The muted-on-muted pair is 4.35:1 by arithmetic (below 4.5), but no rendered text uses it: the chip is `text-foreground` on `bg-muted`, and the skeleton has no text | Step 6 adds the measurement as a test whose result goes through the same ratchet; the muted pair is recorded as "not rendered" |
| P11 | Step 4: "A keyboard-only journey through the filter header and a show block" | The requirement names **visible focus "not covered by sticky headers"** (WCAG 2.4.11, new in 2.2), and the calendar has sticky date headings. Nothing in the plan checks for coverage, and Playwright's `toBeVisible()` ignores overlap | K2 |
| P12 | Step 4: "Reflow at 320px and 375px: no page-level horizontal scroll" | Sound, but it quietly relies on a position the plan never states: the venue rows scroll sideways **on purpose** (requirements: "horizontally scrolling row of venue columns"). WCAG 1.4.10 allows two-dimensional content as an exception; whether this layout qualifies is a judgement | D6, K3. Prototype: no route scrolls the page sideways at 320 or 375 |
| P13 | Nothing on how `incomplete` axe results are handled | axe returns a third bucket for what it could not decide. Two venue links at 375px came back "partially obscured by another element" (fact 4) | Policy in "The ratchet" below: recorded and triaged by hand, not failed |
| P14 | Nothing on CI, `make check`, `.gitignore`, `turbo.json` | Each needs a decision or a change: the CI job design is the plan's own stated open question; `make check` claims to mirror CI; ESLint (`--max-warnings 0`) rejects undeclared env vars in `playwright.config.ts` (fact 11); `playwright-report/` and `test-results/` are not ignored | D4, steps 1 and 7 |
| P15 | "Steps 1–5 below" | There are six steps; and Step 1 says "nothing else is added until it is green" while the item above it adds `@axe-core/playwright` in the same step | Axe lands in this plan's Step 3. "Three runs in a row … in CI" is read as one CI job run with `--repeat-each=3` on Step 1's commit, because a CI "run" is a push |
| P16 | Step 5/6: findings "Ari marks", fixed "before the step closes" | `/build-milestone` runs unattended and stops at sign-off, so a mid-step mark cannot happen inside one run | D9: two implementation rounds, which `AGENTS.md` already allows |
| P17 | `arch-initial.md` §4 libraries table: Playwright is "already a dependency for the agent pipeline's headless fetch" | That is the **Python** package (`playwright>=1.62.0` in `apps/api/pyproject.toml`). The JS runner is a separate, new dependency in `apps/calendar` | Departure 9 (one row) |

## Checked before planning

Everything below was run in a **throwaway `git worktree`** (`pnpm install --frozen-lockfile`, then `@playwright/test` and `@axe-core/playwright` added there only), against the real FastAPI app and a production `next build`/`next start`, on this sandbox's Node 22.22.0. The worktree and every probe were deleted afterwards; **no probe is in the repo**, so the build re-derives each number rather than trusting this table. CONFIRMED means run and read.

| # | Fact | Evidence | Consequence |
|---|---|---|---|
| 1 | **Versions.** `@playwright/test` 1.64.1 and `@axe-core/playwright` 4.14.0 (axe-core 4.14.0), the latest on npm today; `@axe-core/playwright` peers `playwright-core >= 1.0.0`. `pnpm install` added them in seconds and **downloaded no browser** | CONFIRMED (`npm view`, `pnpm add`). Next has an optional peer on `@playwright/test`, so the lockfile's `next@16.3.0(…)` key gains a `(@playwright/test@1.64.1)` suffix: cosmetic churn | Dependencies approved October 17 |
| 2 | **The sandbox cannot download Playwright's browser** (`playwright install chromium` → "Download failure"). It has an older preinstalled Chromium (`/opt/pw-browsers/chromium`, build 1194; Playwright 1.64.1 wants 1248). **That older build ran every probe correctly** | CONFIRMED | `launchOptions.executablePath` from an env var, `E2E_CHROMIUM_PATH`. CI and laptops use `playwright install --with-deps chromium` (PLAUSIBLE: not verifiable here) |
| 3 | **The real API serves the sample data with no database running.** `uvicorn app.main:app` with a dummy `DATABASE_URL` answers `/shows`, `/metro` and the rest; nothing connects | CONFIRMED | D1. The e2e job needs `uv` and Node, not Postgres |
| 4 | **The axe baseline** (tags `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa`; 16 URLs at 1280, 375 and 320 wide): **one rule fires, `target-size` (serious, WCAG 2.5.8)**: artist links in show blocks are `<a class="underline">` **18px high** (needs 24). On `/` (6 nodes), `/day/2026-10-07` and `?sort=time` (2 each), `/artist/1` (2), `/day/2026-10-20` (2); the same at every width. Everything else is clean, including both 404 pages. At 375 and 320, `/` also returns **two `color-contrast` results as `incomplete`** ("background … partially obscured by another element": the Zhora Darling and The Terminal Bar venue links) | CONFIRMED | Findings F1 and F4 below. P13's policy |
| 5 | **A state the static scan misses.** With the Venues combobox popup open, axe reports **`aria-hidden-focus` (serious, 5 nodes)**: Base UI marks `<header>`, `<footer>` and others `aria-hidden` (they carry `data-base-ui-inert`) while they still contain focusable elements. With the Month popup open, only `target-size` | CONFIRMED that it fires; root cause (library behaviour, a prop, or a false positive) **not investigated** | F2. Step 5 scans open popups |
| 6 | **No dark mode.** The `<html>` class is `font-sans …` with and without `prefers-color-scheme: dark` emulation (background stays white). Adding `.dark` by script applies the palette, and that scan is clean, but it is a state no user can reach | CONFIRMED | D7 |
| 7 | **The clock.** The Today row (`aria-current="date"`) is **Mon, Oct 19** today (the real date). The "Showing" range is the pinned Sep 28 – Oct 25. Preloading `Date.now = () => FROZEN` into the Next server with `NODE_OPTIONS=--import` moves the row to **Wed, Oct 7**, with no production-code change. **Subclassing `Date` instead crashes the app** (`TypeError: Date.UTC is not a function` while the Temporal polyfill loads) | CONFIRMED | D2; the gotcha goes in `notes.md` |
| 8 | **Painted focus indicators**, measured as the pixels that change between an unfocused and a focused screenshot of the same clip: artist link, nav link and day-heading link all change white → rgb(208,208,208) = **1.54:1**; the Month select's border goes 229 → 181 = **1.63:1**. (The prototype focused the wrong element for the Venues combobox, so its ring is unmeasured.) `--ring` itself is 2.58:1 on white, but the app paints the link outlines at 50% alpha (computed `outline-color` is the ring colour at 0.5). Unfocused control borders (`--input`, 229) are **1.26:1** on white. `--muted-foreground` on `--muted` is 4.35:1; on the background, 4.74:1 | CONFIRMED (two earlier methods, edge-band sampling and computed styles, disagreed and were abandoned: text and underline pixels contaminate the first, and the second reads the unpainted token) | F3, F6. Method for Step 6. WCAG 1.4.11 asks 3:1 of the visual information that identifies a focused control: CONFIRMED the numbers, **PLAUSIBLE** that this is how Ari reads the criterion, so the severity is his call |
| 9 | **Skeleton and streaming.** The skeleton (`CalendarSkeleton`) is `aria-hidden="true"` with no text. A delay proxy between Next and the API (`POST /__delay/1500`) makes the shell paint at ~0.3–0.7 s, the skeleton stay for the delay, then articles replace it: **3 of 3 repeats** passed. A browser-side `page.route` cannot do this: the fetch happens on the Next server | CONFIRMED | D8; the delay proxy |
| 10 | **Reflow and focus.** No page-level horizontal scroll at 320 or 375 on any of the 16 URLs (`scrollWidth == clientWidth`). Tabbing 159 stops on `/`: at 1280, no stop's centre is covered; at 375, no centre is covered but **9 stops have a corner under a sticky heading** (WCAG 2.4.11 AA asks only that the control not be *entirely* hidden, so this passes; the AAA sibling would not) | CONFIRMED (the prototype's predicate also accepted `top.contains(el)`; the stricter form K2 uses was **not** run) | K2, K3 |
| 11 | **Tooling fits, with four wrinkles.** Vitest ignores `e2e/*.spec.ts` (its include is `**/*.test.ts`; 337 tests still pass with the folder present); **Playwright, by default, collects `*.test.ts` too** (found in review round 1), so it needs `testMatch`. `tsc` and ESLint do cover `e2e/` (tsconfig `include: **/*.ts`; strict indexing applies). **ESLint with `--max-warnings 0` fails** on `process.env.E2E_*` in `playwright.config.ts` (`turbo/no-undeclared-env-vars`), and on the `.mjs` support files, where `process` is `no-undef` (review round 1). `.gitignore` has no `playwright-report` or `test-results` | CONFIRMED | Step 1 sets `testMatch`, declares the variables in `turbo.json` (`globalPassThroughEnv`), adds a Node-globals block for `.mjs`, and ignores the output folders. Pure helpers placed in `e2e/support/*.test.ts` run in `pnpm test` with no browser (K1) |
| 12 | **Cost.** `next build` 26 s here. The 16-URL axe sweep took ~26–28 s per width, ~1.7 s a page; the prototype waited on `networkidle`, the build waits on content (ground rule 7) | CONFIRMED | Suite estimate ~2–3 min plus the build: PLAUSIBLE until measured. The every-screen scan runs at 1280 and 375, reflow only at 320 |
| 13 | **Selectors for the journeys.** `<article>` per show block (25 on `/`); the filter controls are labelled `Venues`, `Artists`, `Month`; the day view's three sort links are `By venue` / `By time` / `By artist`, the current one `aria-current="page"`; `role="status"` holds "Updating…"; the 404 heading is "Not found" with a link "Back to the calendar" | CONFIRMED by reading `filter-header.tsx`, `day/[date]/page.tsx`, `not-found.tsx` | Every locator is role- and name-based (the B5 rule) except the skeleton, until D8 |

### Findings the prototype already has (the baseline's first rows)

These are the content of the findings table the build records, with a **proposed** severity (Ari marks them, D9). IDs are `B6-F<n>`.

| ID | Finding | WCAG | Found by | Proposed |
|---|---|---|---|---|
| F1 | Artist links in show blocks and day/artist lists are 18px high | 2.5.8 AA | axe `target-size` | must-fix: an AA failure, and `/day/[date]` already solved it (`inline-block py-1`) |
| F2 | `aria-hidden-focus` while a combobox popup is open | 4.1.2 A | axe, popup state | should-fix until the cause is known: may be upstream |
| F3 | Focus indicator is 1.54:1 (links) and 1.63:1 (Month select); Venues combobox unmeasured | 1.4.11 AA | Step 6 measurement | must-fix if Ari reads 1.4.11 as covering focus rings (the W3C Understanding document does) |
| F4 | Two venue links' contrast undecidable at ≤375px ("partially obscured") | 1.4.3 AA | axe `incomplete` | to triage by eye |
| F5 | The skeleton is silent: no status text while the calendar loads | 4.1.3 AA (judgement) | by reading, P7 | markup fixed in round 1 by D8 (its approval is the mark); whether anything is announced stays in the manual pass |
| F6 | Unfocused control borders are 1.26:1 on white | 1.4.11 AA | Step 6 measurement | should-fix or nit: depends on whether the label alone identifies the field |

Not findings, recorded so nobody re-checks them: reflow at 320/375 passes everywhere; focus is never entirely hidden; both 404 pages are clean; `bypass`, `document-title`, `html-has-lang`, `label`, `link-name` and `button-name` pass on every screen.

## Departures from the build plan (to apply to `alpha-build-plan.md` when implementing)

1. **Rewrite the "Standing rule: the test clock" and "Known date cliff" paragraphs** (P1), and the `notes.md` section of the same name (in place, confined to those B6-owned paragraphs, to stay small per `AGENTS.md`'s parallel-tracks rule): the API window is pinned; the Next server's `metroToday` is the one clock; the rule is "one constant, guarded by a unit test"; the cliff arrives with A1b.
2. Step 1 includes the `make e2e` target, the CI job, `.gitignore`, `turbo.json`. `@axe-core/playwright` is installed in Step 3, not Step 1 (P15). "Three runs" is `--repeat-each=3`.
3. Step 1's stack option is **the real API on `sample_data.py`** (P2, D1).
4. **Dark mode is dropped** from Step 4 (P3, D7).
5. The journey table is corrected and extended (P4–P7): J3's note, J6 split in three, the busy state (J8) and the skeleton (J9) share a delay proxy, a Back-button journey (J4) is added (B3-D8: push, not replace, is what makes Back undo a filter; jsdom cannot show history).
6. Step 2's "report-only" becomes a **ratchet baseline** (P9, D5); Step 5 gains every-screen and popup-state scans (P8); Step 4 gains the focus-not-obscured check (P11) and the painted-focus measurement (P10); `incomplete` results get a policy (P13).
7. Step 5 ("Run, review, resolve") becomes a **second implementation round** after Ari's marks (P16, D9).
8. Marking: Steps 1, 3, 4, 5, 7 and 8 [written]; three `TODO(Ari)` gaps (K1 in Step 2, K2 and K3 in Step 6) [fill-in] (D10).
9. Docs and scripts: `arch-initial.md` §4 libraries row (P17); `scripts/cloud-setup.sh` exports `E2E_CHROMIUM_PATH` (review finding 7); `nextjs-style-guide.md` Testing paragraph ("Playwright is still deferred"); `apps/calendar/AGENTS.md` (an E2E section: stack, ports, the clock, the proxy, `E2E_CHROMIUM_PATH`); root `AGENTS.md` "Cloud sessions" (e2e runs there, with `E2E_CHROMIUM_PATH=/opt/pw-browsers/chromium`); `conventions.md` scope table (a `B6` row) and the `F` form widened to "a failure found in an eval, or by a scan or check (`B6-F2`)"; `notes.md` (the clock section rewritten; the `Date`-subclass gotcha; `pkill -f` is already there).

## Decisions for the user / reviewer

**Settled by Ari, October 19, 2026: D1–D10 are accepted as recommended, and the plan is approved for implementation, with one addition (D11).** Each decision below keeps its recommendation and its alternative on record. **Ari: D1, D2, D4, D5, D6 and D9 change what gets built or how it is run; the rest are low-stakes.**

- **D1 — The stack the tests run against. Recommended: the real FastAPI app serving `sample_data.py`** (P2, fact 3), started by Playwright's `webServer` on dedicated ports (API 8101, proxy 8102, Next 3100, so a running `make dev` is never reused and never collides). *Alternatives:* a stub serving `lib/fixtures` (the fixtures are response bodies, not the logic that picks them, so the stub would re-implement the filters, ranges, `upcoming`, 404s and 422s, and could drift); or wait for A1b and use a seeded Postgres (blocks B6 on another milestone, and the seed has no shows). *Consequence of the recommendation:* when A1b swaps the routers onto the database, the e2e job gains a Postgres service and a deterministic show seed; A1b already has an open item about keeping a sample-data source (build plan A1b, last bullet), and this strengthens it (Follow-ups).
- **D2 — How the clock is pinned. Recommended: a test-only `--import` preload on the Next server that patches `Date.now`** (fact 7), the pin held as one constant (`2026-10-07T17:00:00Z`, noon Wednesday in Minneapolis, inside the sample window with five shows on it) and **guarded by a Vitest test** that fails when the pin leaves the fixtures' window or its date has no show. *Alternatives:* an env override read by the app (a production hook that exists only for tests); or no pin and no assertion on the Today row (loses the only browser-level check of `aria-current="date"`). Note the guard replaces the build plan's "move the pin in the same change" memo with a red test.
- **D3 — Production build or dev server. Recommended: `next build && next start`.** It is what visitors get (streaming, no development overlay). *Alternative:* `next dev`: no build step, but Next's dev tooling injects its own elements into every page, which would put findings in the scan that no visitor sees (PLAUSIBLE; not measured). Cost: a 26 s build before each run.
- **D4 — CI and `make check`. Recommended:** a separate `e2e` job in `ci.yml` (Node 24, `uv sync --locked`, `playwright install --with-deps chromium`, a cache for the browser, the report uploaded on failure), and `make e2e` added to `make check` so "everything CI runs" stays true. *Alternatives:* fold it into the `js` job (slower feedback for every JS change; needs Python there); or leave `make check` without it and say so in the Makefile header (`check` then no longer mirrors CI). The branch has no protection yet (`env-setup.md`), so "the build fails" means a red job.
- **D5 — Report-only or ratchet. Recommended: a ratchet baseline** (P9; explained with examples under "The ratchet" in the harness design). In short: a committed list of the known accessibility problems that the scan must match exactly, so anything worse fails and each fix becomes a red-then-green step. *Alternative:* report-only until the findings are fixed (nothing fails until a later change flips a switch, so a new violation can land in the meantime).
- **D6 — Reflow and the sideways-scrolling rows. Recommended:** treat each venue row's own scroll region as WCAG 1.4.10's two-dimensional-content exception, assert only that the **page** never scrolls sideways (K3), and rely on axe's `scrollable-region-focusable` plus the keyboard pass to confirm each scroller is reachable. *Alternative:* stack the venue columns vertically below 320px (a layout change to the B3 design, which is Ari's). Ari's call because it is a reading of a criterion about his own design.
- **D7 — Dark mode. Recommended: drop it from B6** (P3). Add it to the scan matrix if the app ever gets a theme switch. *Alternative:* scan a forced `.dark` page anyway: it is clean today and describes a state that does not ship.
- **D8 — The skeleton's handle. Recommended: a visually hidden `role="status"` paragraph "Loading shows" beside the decorative bars** (which stay `aria-hidden`). It gives a role-based test its locator, and a screen-reader user who browses the page finds a loading state (F5). It does **not** promise an announcement: a live region already present in the first HTML with its text is generally not announced, and neither is its removal (PLAUSIBLE; not run in a screen reader), so whether anything is spoken stays a manual-pass question and `aria-busy` on the results region is the other common pattern. Same shape as B5-D3 (a defect found while writing tests, fixed with a test first). It touches `calendar-skeleton.tsx` and its message. **Approving D8 is the mark** for this one production change, so it is made in round 1 (Step 5) and F5 is recorded as "markup fixed by D8", not left for Ari to mark again. *Alternatives:* a `data-testid` (breaks the project's "role, name or label only" rule and leaves F5); a class selector on `animate-pulse` (brittle, same).
- **D9 — Process around findings. Recommended: two implementation rounds.** Round 1 builds Steps 1–7, records the findings table with proposed severities, passes code review, and stops at `Awaiting sign-off` with the **marking request first in the handoff**. Ari marks F-items; round 2 (Step 8) fixes the marked ones, each in its own commit, test first, then sign-off. This uses `AGENTS.md`'s existing "second implementation pass gets its own log round", and honours the build plan's "Ari marks, then fixed" without a mid-run stop. *Alternatives:* the build run fixes everything it proposes as must-fix without waiting (WCAG AA is already a stated requirement, so the decision could be treated as made, but the build plan says Ari marks); or a mid-build stop after Step 3 (changes the cycle's gates). One exception to "nothing is fixed before Ari marks it": D8's skeleton markup, because approving D8 is its mark.
- **D10 — Marking. Recommended: K1–K3 [fill-in]; everything else [written].** K1 (the clock pin) is the server/browser split this project exists to teach: Server Components run on the Next server, so the browser's clock tools cannot reach them. K2 (the focus-obscured predicate) is a lesson about *what the check means*. K3 (the reflow predicate) is the weakest (two lines); if Ari wants fewer gaps, drop K3 and keep it [written]. **The ratchet comparison was a candidate and is [written] on purpose** (plan review round 1, finding 1): while open, every axe-backed test would throw, so the baseline rows and most of Steps 3, 5 and 6 could not be verified. *Alternative:* all [written], which `AGENTS.md` allows when no line carries a lesson; this plan thinks two do.
- **D11 — A pause after Step 1's first green test. Decided: yes (added by Ari, October 19, 2026).** This is Ari's first time with Playwright, so when Step 1's one end-to-end test is green the build **stops and hands off**: Ari checks the branch out (or `claude --teleport`) and runs that test himself to get a feel for it, then tells the next session to continue with Step 2. The branch is committed and pushed at the pause (a cloud session's work only reaches Ari through the branch, `AGENTS.md` "Cloud sessions"). Nothing after Step 1 is started before then. *Consequence for the cycle:* the build is no longer one run. The Implementation log gets a round per run (this pause is round 1, scoped to Step 1), and **the second-model code review waits until all implementation is finished** (Ari: no mid-build review), so the review round covers Steps 1–7 together. Ari's D9 findings-marking gate is unchanged.

## WCAG 2.2 AA coverage matrix

How each criterion that applies to this app is checked. **Automated checks are a floor** (`arch-initial.md` §4). "axe" means the scan with tags `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa`; "custom" means a check B6 writes because axe has no rule; "manual" means Ari's pass.

| Criterion | Level | How it is checked |
|---|---|---|
| 1.1.1 Non-text content | A | axe (`image-alt`); manual: is each alt text meaningful (venue photo "Photo of …", poster alt) |
| 1.3.1 Info and relationships | A | axe (lists, definition lists, labels); manual: heading outline (h1, a date h2 per row, venue headings) |
| 1.3.2 Meaningful sequence | A | manual: DOM order reads sensibly (date, venue, show); the keyboard journey logs the order |
| 1.3.3 Sensory characteristics | A | by inspection: no instruction relies on shape, position or colour alone; manual |
| 1.4.1 Use of colour | A | axe `link-in-text-block`; links are underlined; manual |
| 1.4.3 Contrast (minimum) | AA | axe `color-contrast` on rendered pairs, every screen, popup states; **incomplete** results triaged by hand (F4) |
| 1.4.4 Resize text | AA | manual (200% browser zoom); the 320px reflow run covers 400% |
| 1.4.5 Images of text | AA | manual: posters on the show page carry text, and the same information is in the page's HTML (the show's lineup and times) |
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
| 2.5.2 Pointer cancellation | A | by inspection: links and buttons act on release; Base UI popups open on pointer-down, like a native select (PLAUSIBLE); manual |
| 2.5.3 Label in name | A | by inspection (axe's rule for it is experimental and not in the tags): the filters' visible labels are their names, and "9:00 PM – 11:30 PM, show details" starts with its visible text |
| 2.5.7 Dragging movements | AA | N/A: nothing needs dragging (the rows scroll natively) |
| 2.5.8 Target size (minimum) | AA, new in 2.2 | axe `target-size` (it is in the `wcag22aa` tag): F1 |
| 3.1.1 Language of page | A | axe `html-has-lang` |
| 3.1.2 Language of parts | AA | by inspection: venue and artist names are proper nouns; scraped text is English |
| 3.2.1 On focus | A | keyboard journey: focusing a control (Tab, arrows in a popup) never navigates or changes the page by itself |
| 3.2.2 On input | A | **manual judgement**: picking a filter navigates and re-renders without a submit button; is that a change of context that needs advance notice? The Updating… status helps (4.1.3) |
| 3.2.3 / 3.2.4 Consistent navigation / identification | AA | by inspection (one root layout) |
| 3.3.2 Labels or instructions | A | axe `label`; the filters are the only inputs |
| 4.1.2 Name, role, value | A | axe (`aria-*`, `button-name`, `aria-hidden-focus`): F2; the chip-remove names (B5-D3) are asserted in J2 |
| 4.1.3 Status messages | AA | J8 asserts the status region's text appears and clears; **whether a screen reader announces it, and "No matches found", is manual**; F5 |
| N/A for this app | — | 1.3.4 and 1.3.5 (no orientation lock, no personal-data fields), 2.1.4 (no character shortcuts), 2.2.x (no time limits), 2.3.1, 2.5.1 and 2.5.4 (no custom gestures or motion input), 3.2.6 (no help mechanism), 3.3.1, 3.3.7, 3.3.8 (no authentication), 1.2.x (no media) |

## Design of the harness

### Layout (all under `apps/calendar/`)

```
playwright.config.ts            one project (chromium, desktop), testMatch "**/*.spec.ts", workers 1, retries 0, webServer ×3
e2e/
  support/
    stack.ts                    ports, URLs, the control client for the proxy
    clock.ts                    the one pinned instant (D2)
    clock.test.ts               Vitest: the pin lies inside the fixtures' window and on a day with a show
    fake-now.mjs                the preload: Date.now only
    delay-proxy.mjs             pass-through proxy: POST /__delay/<ms>, /__fail, /__reset
    test.ts                     `test` extended with a fixture that resets the proxy after every test
    a11y.ts                     AXE_TAGS, scanPage(): axe result → Finding[]
    a11y-baseline.ts            compareToBaseline() and the committed BASELINE
    a11y-baseline.test.ts       Vitest: the comparison, with hand-made findings
    focus.ts                    isFocusObscured() (K2); focusIndicatorContrast() (screenshot diff)
    reflow.ts                   expectNoPageReflow() (K3)
  home.spec.ts … (one file per journey, below)
```

Specs are `*.spec.ts`; unit tests of the helpers are `*.test.ts` (Vitest's `unit` project picks them up, so they run in `pnpm test` with no browser and in `make check`). Each runner must be told to ignore the other's files. Vitest already does (its `include` is `**/*.test.ts`). **Playwright does not by default**: its default `testMatch` is `**/*.@(spec|test).?(c|m)[jt]s?(x)`, so it would try to load `e2e/support/*.test.ts` (which import `vitest`) and list 0 tests. The config therefore sets `testMatch: "**/*.spec.ts"` (plan review round 1, finding 2; reproduced there).

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

**Lint (fact 11).** `turbo.json` declares `E2E_CHROMIUM_PATH` and `E2E_FROZEN_NOW` under `globalPassThroughEnv` (which `eslint-plugin-turbo` reads; an entry under `build.env` would change the build's cache hash for variables the build never reads). The two `.mjs` support files need Node globals: the shared ESLint config gives `.mjs` files only `globals.serviceworker`, so `process` is `no-undef`. `apps/calendar/eslint.config.js` gets a scoped `globals.node` block for `e2e/**/*.mjs`. `pnpm lint` must pass with zero warnings before Step 1 is done. `.gitignore` gains `playwright-report/` and `test-results/`.

**Cloud sessions.** `make check` includes `e2e` (D4), and a cloud session has no `E2E_CHROMIUM_PATH` and not the browser build Playwright 1.64 wants (fact 2). `scripts/cloud-setup.sh` exports `E2E_CHROMIUM_PATH=/opt/pw-browsers/chromium` through `CLAUDE_ENV_FILE` when that file exists, the same mechanism it already uses for `PATH` (PLAUSIBLE that the export reaches `make check`; the build verifies it from a fresh shell). Without it every later cloud `make check` would fail on a missing browser (plan review round 1, finding 7).

### The ratchet (D5)

**In one sentence:** a committed list of the accessibility problems we already know about, which the scan must match *exactly*: anything worse than the list fails, and anything better than the list also fails until the list is updated.

#### The problem it solves

The scan produces a list of violations, and today it is not empty (F1 and F2 below). There are three ways to turn that list into pass or fail, and two of them do not work:

| Approach | What happens | Why it falls short |
|---|---|---|
| "Fail if there are any violations" | Red from the first commit | Nothing can merge until every finding is fixed, and Ari has not yet marked which ones to fix (D9) |
| "Report only" (the build plan's wording) | Always green | A brand-new violation can land and nobody is told |
| **A ratchet** | Green today, red the moment things get worse | Needs one small committed list, the baseline |

#### What the baseline holds

One row per page per rule: `{ page, ruleId, nodes }`, where `nodes` is how many elements on that page break that rule. Each row also names the finding (`B6-F<n>`) it belongs to. For example, the prototype's first finding:

```
rule: target-size    page: /    nodes: 6    finding: B6-F1
```

The axe results become rows like this (`ruleId` is the axe rule). The custom checks (reflow, painted focus-ring contrast) produce rows of their own (for example `ruleId: "b6-focus-indicator-3to1"`, with `nodes` = how many of a fixed list of focus targets fall below 3:1), so **one baseline governs both**.

#### The three outcomes

Every scan is compared with the baseline. The test fails on anything other than an exact match:

| The scan shows | Verdict | What it means | What you do |
|---|---|---|---|
| Exactly what the baseline lists | pass | Nothing changed | Nothing |
| A rule that is not in the baseline, or more elements than the row lists | fail: **added** | Something got worse | Fix the new problem. The baseline is not edited to make room for it. |
| A row whose problem is gone, or fewer elements than the row lists | fail: **stale** | Something got better | Lower or delete that row. This is the "ratchet click": the list can shrink and never grow back. |

#### Why a fix makes the test fail, with numbers

The "stale" outcome is the part that feels backwards. Take the row above (`target-size` on `/`, 6 elements):

| Step | What happens | Scan finds | Verdict |
|---|---|---|---|
| Today | Baseline says 6 | 6 | pass |
| Someone fixes 2 links | The page is better | 4 | **stale**: lower the row to 4 |
| *(without a stale check)* someone then adds a new 2-element problem of the same rule | The page is worse again | 6 | A looser "no more than 6" rule would **still pass**, and the new problem is hidden |
| *(with the stale check)* the row was forced down to 4 | The new problem makes it 6 | 6 vs 4 | fail: **added**. It is caught |

So the exact-match rule is what closes the gap a "no more than N" rule leaves open. Counting elements, not just rule names, closes the other one: without it, a rule could grow from 2 elements to 20 and still be "known".

#### How a fix works with it

Every fix in the fix round (Step 8) follows the same three steps, and the first two are the "test that fails before the fix" the build plan asks for:

1. Delete the finding's baseline row. The test goes red, because the scan still sees the problem.
2. Fix the code. The test goes green.
3. The row never comes back, so a regression of the same rule shows up as **added**.

#### What it does not do

- It does not say the known problems are acceptable. They stay on the list until Ari marks them and the fix round removes them.
- It does not find anything axe cannot. The custom checks feed the same list, and the manual pass covers the rest (the coverage matrix).
- `incomplete` results (axe could not decide, finding F4) are not in the baseline. They are attached to the test report and triaged by hand in the log (P13).

#### The name

"Ratchet" is an informal industry term for this pattern, not a standard: like a ratchet wrench, the count of known problems can only move one way. The same idea goes by other names, and the plan uses "ratchet" and "baseline" for the two halves (the rule, and the list it holds). Notion's engineering blog describes a "ratcheting system" for lint rules with a committed file of allowed violation counts per file and rule, which CI enforces and which fixes lower. ESLint ships the same thing built in as *bulk suppressions* (`eslint-suppressions.json`, counts per file and rule; ESLint 9.24 and later). Android Lint calls it a *baseline* (`lint-baseline.xml`). The one thing this plan adds to the common form is the **stale** half: many tools only fail on *added* problems, and this one also fails when the list is out of date, so it cannot drift.

#### The comparison itself

`compareToBaseline(found, baseline)` is written complete and unit-tested (`a11y-baseline.test.ts`; it was a candidate `TODO(Ari)` gap and is not one, D10). The test cases are the table above: equal, a new rule, more elements, a fixed row, fewer elements, and two pages with the same rule treated independently.

```ts
const key = (e: Finding) => `${e.ruleId}@${e.page}`;
const known = new Map(baseline.map((e) => [key(e), e.nodes]));
const seen = new Map(found.map((e) => [key(e), e.nodes]));
return {
  added: [...seen].filter(([k, n]) => (known.get(k) ?? 0) < n), // new, or more elements than known
  stale: [...known].filter(([k, n]) => (seen.get(k) ?? 0) < n), // fixed, or fewer elements than known
};
```

`expectBaseline(page, name)` runs the scan, calls this, and fails if either list is non-empty, printing both so the message says which kind of failure it is.

## Test approach (written first, watched fail, then made green)

For a browser test "red first" means one of three things, and each step says which: the stack isn't wired (the first test), the expectation is wrong until the pin or the feature exists (the Today row; the skeleton's status), or a deliberate break proves the test can fail (the mutation table, Verification 4).

**Ground rules** (carried from B5, plus three): (1) locate by role, accessible name or label, never a class, `data-slot` or test id; (2) assert the whole outcome (the full URL, the exact heading, the exact count); (3) expected values are written literally in the test with their source in a comment and are never read from the code or the fixtures under test (B5's reasoning: a test that reads its expectation from what it checks cannot catch it being wrong); (4) one journey, one test, one story; (5) every test opens with a `Proves:` comment; (6) no snapshot tests; (7) no `waitForTimeout` and no `networkidle` (Playwright discourages it, and `<Link>` prefetching keeps a production page's network busy): before any assertion or scan, wait on the content, the h1 and the expected article count, which also guarantees a scan sees the calendar and not the skeleton.

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
- **`e2e/support/a11y-baseline.test.ts`:** equal sets → nothing added, nothing stale; a rule absent from the baseline → added; more nodes → added; an entry the page no longer has → stale; fewer nodes → stale; two pages with the same rule are independent. *Proves:* "fails on a new violation" and "a fix is a red→green step" are true and cannot be traded for each other. Expected values are hand-made findings.

### Browser tests (each opens with `Proves:`; selectors per fact 13)

| # | File and journey | Proves | Needs |
|---|---|---|---|
| J1 | `home.spec.ts`: `/` shows "Live music" and the calendar, and the Today row is the pinned date | Step 1: the page loads end to end; with the pin: `aria-current="date"` is on "Wed, Oct 7 Today" and that row holds five articles (the 25 total is asserted too). Red without the pin (today it is Mon, Oct 19) | stack; pin (Step 2) |
| J2 | `filter-venue.spec.ts`: pick "The White Squirrel Bar" in Venues | the URL becomes exactly `/?venue=1`; a chip and a button named "Remove The White Squirrel Bar" appear; only that venue's shows remain (8 of the 25, B5 fact 13); the real router, streaming and optimistic chip work together (B5 backlog) | stack |
| J3 | `filter-empty.spec.ts`: Midway + Charlie Parr | "No matches found." and a link "Reset filters" to `/`; following it restores all 25 shows (the filtered-empty branch B5 could not reach end to end, P4) | stack |
| J4 | `filter-history.spec.ts`: pick a venue, then Back | the URL returns to `/`, the chip is gone and 25 shows are back (B3-D8: `push`, not `replace`; the one history behaviour jsdom cannot see). Not in the build plan; added | stack |
| J5 | `day-view.spec.ts`: `/day/2026-10-07`, then By time, By artist, By venue | each link's URL (`?sort=time`, `?sort=artist`, the bare URL); `aria-current="page"` moves; the first and last rows in each order (written out); the default has one URL (B4-D6) | stack |
| J6a | `venue-page.spec.ts`: from `/`, in the Today row (`getByRole("listitem", { current: "date" })`, scoped because the venue name heads a column in every date it plays), click the "Zhora Darling" link | `/venue/3`, h1 "Zhora Darling", its shows listed | stack; pin |
| J6b | `artist-page.spec.ts`: from `/`, in show 2's article (the `article` that contains the link named "9:00 PM – 11:30 PM, show details"; scoped because Beasthead plays shows 2 and 8) click "Beasthead" | `/artist/9`, h1 "Beasthead", its upcoming shows | stack |
| J6c | `show-page.spec.ts`: from `/`, click show 2's time link | `/show/2`, the lineup and time shown, and a page title written out from B4-D7's format (`<names> at <venue>, <weekday, month day, year>` plus the layout's `· Agentic Live Music Calendar` suffix; the format is cited in the test's comment, and a mismatch with the page is investigated, never copied into the test) | stack |
| J7 | `not-found.spec.ts`: one generated test per URL (`/venue/9999`, `/venue/abc`, `/day/2026-02-30`, `/nope`) | HTTP **404** (not a soft 200) with h1 "Not found" and a link back (B2: `notFound()` must throw). Valid only while detail routes are not behind a streaming boundary (B2-D4 note) | stack |
| J8 | `filter-busy.spec.ts`: delay 1500 ms, pick a venue | `aria-busy="true"` and the status text "Updating…" appear, then clear when the page settles (`aria-busy` goes to the string `"false"`, it is not removed, and the status text goes empty: `filter-header.tsx` always renders the status element); the chip shows at once (the optimistic value) and stays (B5 fact 12, finally observable) | proxy; delay |
| J9 | `skeleton.spec.ts`: delay 1500 ms, load `/` | the shell and heading are visible first, the "Loading shows" status is present and no article exists; then the articles appear and the text "Loading shows" is gone (assert on the **text**, not on a status role disappearing: the filter header always renders its own empty `role="status"`). B3-D4; red until D8's markup exists | proxy; D8 |

The scans (Step 3 and 5), reflow and keyboard checks (Step 6) are described in the steps.

### What is *not* covered, stated plainly

- Any other browser, any phone or tablet **device** (a narrow viewport is not a phone: touch, the on-screen keyboard and the real scroll feel are the manual pass).
- Whether a screen reader says anything sensible (the matrix's manual rows).
- The unfiltered empty message ("No shows listed for these dates"): no sample window is empty (B5 fact 14); it stays covered by B5-K3 in Vitest.
- The API-down experience beyond the one error-screen scan; the detail routes' bare 500 (a known B2 behaviour) is not a screen to scan.
- Hover and pressed states (the scan sees the DOM at rest and in the states the tests reach).
- A second, slower run of axe in other languages or zoom levels.

## TODO(Ari) gaps

Three blocks, all in test-support code, **independent of each other and of every scan**: each open gap reddens only its own test (K1 → J1's Today row; K2 → the keyboard test; K3 → the reflow test), so the rest of the suite stays verifiable (plan review round 1, finding 1). Each is a few lines.

- **K1 — the clock pin in `e2e/support/fake-now.mjs`** (Step 2, [fill-in]).
  *Lesson:* Server Components run on the **Next server**, so "which row says Today" is decided by the server's clock; Playwright's `page.clock` fakes only the browser's and cannot reach it. The pin therefore goes on the Next server process, as a preload that patches `Date.now` and **only** `Date.now`: the Temporal polyfill reads `Date.now()` for `Temporal.Now` (so one line is enough), and a `Date` subclass crashes it at import (`Date.UTC is not a function`, fact 7). `NODE_OPTIONS` is scoped to that one `webServer` entry (written), so the runner itself is not frozen.
  *Code:* `Date.now = () => FROZEN;` (the line above it, `const FROZEN = Date.parse(process.env.E2E_FROZEN_NOW);`, is written).
  *Check:* J1's Today-row assertion (red until filled: the server runs on the real clock, today Mon, Oct 19) and mutation B6-M9. **This placeholder is deliberately a missing line, not a `throw`** (a departure from `AGENTS.md`'s "fail loudly", chosen for blast radius): a throw in a preload kills the Next process and with it every browser test, so one open gap would redden the whole suite. J1 is the loud part. Likeliest mistakes: subclassing or replacing `Date`; reaching for `page.clock.install` (browser only).
- **K2 — `isFocusObscured` in `e2e/support/focus.ts`** (Step 6, [fill-in]).
  *Lesson:* WCAG 2.4.11 (Focus Not Obscured, minimum, new in 2.2): a focused control must not be **entirely** hidden by author-created content, here the sticky date headings (requirements: "not covered by sticky headers"). Playwright's `toBeVisible()` and `toBeInViewport()` ignore overlap, so ask the browser what is on top **at the control's centre**. That is *stricter* than the criterion (a control whose centre is covered but whose corner shows still passes 2.4.11): it is a sufficient check, not the definition, and if it ever goes red at 375px for a control that is partly visible, Ari decides whether to loosen it. Read it after the Tab keypress has resolved, which is after the browser has scrolled the control into view.
  *Code:* `return page.evaluate(() => { const el = document.activeElement as HTMLElement; const r = el.getClientRects()[0] ?? el.getBoundingClientRect(); const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !(top && (top === el || el.contains(top))); });`
  *Check:* `keyboard.spec.ts` "no Tab stop is newly hidden, under a sticky heading or anything else" is red until filled (the placeholder throws) and green on the real page at 1280 and 375, on `/` and on `/venue/1`, **with the baseline row for B6-F7** (one stop on `/` at 375 is reported, by name; found when the plan's code was run, not in the prototype); mutation B6-M6 (a fixed bar over the top of the page) turns it red. `getClientRects()[0]` is the first line box: a wrapped inline link's bounding-box centre can fall between its lines and report a false "obscured" (PLAUSIBLE). Likeliest mistake: `toBeVisible()`; also accepting `top.contains(el)` (a covering ancestor passes). The prototype used a looser three-clause predicate; this stricter one is **unverified until the build runs it** in a throwaway worktree (Verification 4).
- **K3 — `expectNoPageReflow` in `e2e/support/reflow.ts`** (Step 6, [fill-in]; the weakest gap, see D10).
  *Lesson:* WCAG 1.4.10 (Reflow): at 320 CSS px wide the **page** must not need a horizontal scrollbar. The venue rows scroll sideways on purpose inside their own regions (D6), so measure the **document**, not `body` (which `overflow-x: hidden` would hide) and not the scrollers. Set the viewport before navigating, so the layout is computed at that width.
  *Code:* `const { w, c } = await page.evaluate(() => ({ w: document.documentElement.scrollWidth, c: document.documentElement.clientWidth })); expect(w).toBeLessThanOrEqual(c);`
  *Check:* `reflow.spec.ts` (320 and 375, every route) red until filled, green on the real pages (prototype: equal everywhere); mutation B6-M5 (a `min-w-[400px]` element in the header) turns it red. Likeliest mistake: measuring `document.body.scrollWidth`.

## Implementation steps

Order matters: tests first, one green thing at a time, and the full suite run at the end of each step (the build plan's rule). Each step ends green before the next starts, apart from the one test an open `TODO(Ari)` gap reddens on purpose (K1 in Step 2, K2 and K3 in Step 6). **[written]** / **[fill-in]** per Departure 8.

### Step 1 [written] — the harness and one green test
1. Write `home.spec.ts` (J1's first half: `/` shows "Live music" and at least one article) and the config **first**: watch it fail because the stack isn't wired.
2. `pnpm --filter calendar add -D @playwright/test`; `playwright.config.ts` (with `testMatch`); `e2e/support/stack.ts`, `delay-proxy.mjs` (pass-through only for now), `test.ts`; `turbo.json` `globalPassThroughEnv`, the scoped `globals.node` block in `eslint.config.js`, `.gitignore`; the `E2E_CHROMIUM_PATH` export in `scripts/cloud-setup.sh`.
3. `make e2e` (build, then `playwright test`; `.PHONY`; one comment saying what it starts and why on other ports); the `e2e` job in `ci.yml` (D4), carrying `--repeat-each=3` for this commit; `check:` gains `e2e`.
4. **Done when** `pnpm lint` has zero warnings, `E2E_CHROMIUM_PATH=… make e2e E2E_ARGS="--repeat-each=3"` is green here (the target passes `$(E2E_ARGS)` to `playwright test`), no listener remains on 8101/8102/3100, and the CI job is green with the same flag.

### Step 2 [written, K1 fill-in] — the clock pin
`clock.ts`, `clock.test.ts` (red first: no pin), `fake-now.mjs` as a scaffold with K1 (the `FROZEN` line written, the `Date.now` line the gap); wire it into the Next `webServer` env (written); extend J1 to the Today-row assertion (red against the real clock, which is also what an open K1 looks like). Remove `--repeat-each=3` from CI.

### Step 3 [written] — axe on the home page, with the baseline
1. `pnpm --filter calendar add -D @axe-core/playwright`.
2. `a11y-baseline.test.ts` first (red), then `compareToBaseline` written complete (the comparison in "The ratchet"), then `a11y.ts`: `AXE_TAGS` as one constant, `scanPage` turning an axe result into findings and attaching the raw result to the report.
3. `a11y-home.spec.ts`: scan `/` at 1280 against the baseline. The first run is red with F1 as "added" (a real red, because the comparison works); commit the baseline entry (`B6-F1`, `nodes: 6`) with its finding ID.
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
   | Show: timed, untimed, start time only | `/show/2`, `/show/3` (untimed, from `shows.json`), `/show/22` (starts 6:00 PM, no end) |
   | Diagnostics | `/health` |
   | 404 | `/nope` |
   | Error screen | `/` with the proxy in `__fail` mode (the shell and the error boundary after hydration: PLAUSIBLE from `apps/calendar/AGENTS.md`; confirm at build) |
4. `a11y-popups.spec.ts`: the Venues popup open, the Artists popup open with one option highlighted by keyboard, the Month popup open (fact 5): F2's baseline row.
5. `incomplete` results are written to the log as a table (page, rule, element, reason) for triage (F4).

### Step 6 [written, K2 and K3 fill-in] — layout, keyboard, painted focus
1. `reflow.spec.ts`: every route at 320 and 375 with `expectNoPageReflow` (K3 scaffold, red until filled).
2. `keyboard.spec.ts`: Tab through the home page **and `/venue/1`** (it renders the same `CalendarGrid` with the same sticky heading) from the top at 1280 and 375, reading `isFocusObscured` after each stop (K2 scaffold) and logging the visited order; then the filter header by keyboard only (open Venues with the keyboard, pick with Enter, Esc closes and focus returns, the Month select by keyboard) and a show block's link by Enter. This is 2.1.1, 2.1.2 and 2.4.3's evidence.
3. `focus-indicator.spec.ts`: for a fixed list of targets (an artist link, a nav link, a day-heading link, the Venues combobox, the Month select, "Clear filters" on a filtered page), measure the painted indicator by **diffing a focused against an unfocused screenshot of the same clip** (fact 8), and report the unfocused control border too. Targets below 3:1 become a custom finding (`b6-focus-indicator-3to1`, F3) and the borders another (`b6-control-border-3to1`, F6), both in the baseline. The measured values are written into the log. **Pixels are decoded in the browser**: each screenshot's base64 PNG is drawn onto a canvas inside `page.evaluate` and read with `getImageData` (what the prototype did), so there is no decoder dependency and the two approved dependencies stay two. The Venues combobox's first measurement is taken here, on the right element.

### Step 7 [written] — docs, mutation pass, handoff
Departure 1–9's docs; the mutation table (Verification 4) run and recorded; the **findings table** (F1–F6 and anything Step 5–6 added, with measured values, proposed severity and the proposed fix in one line each); the manual-pass script (Verification 7) ready for Ari. Then `make check`, the Implementation log round, and Status `Code review`.

### Step 8 [written] — the fix round (a second implementation round, after Ari's marks, D9)
For each finding Ari marks must-fix or should-fix: delete its baseline row (the red test), fix, green, **its own commit**. Findings marked nit or left unmarked are logged and keep their baseline row. F1's fix is one class change (`inline-block py-1`, the day view's pattern, B4); F3/F6 touch shared tokens or `packages/ui`; F2's cause has to be found first.

## Critical files

| File | Why |
|---|---|
| `apps/calendar/playwright.config.ts`, `e2e/**` (new) | the whole milestone |
| `apps/calendar/package.json`, `pnpm-lock.yaml` | two dev dependencies |
| `Makefile`, `.github/workflows/ci.yml`, `turbo.json`, `.gitignore`, `apps/calendar/eslint.config.js`, `scripts/cloud-setup.sh` | `make e2e`, the CI job, env declarations, Node globals for the `.mjs` files, ignored output, the browser path in cloud sessions |
| `apps/calendar/app/_components/calendar-skeleton.tsx` (+ test) | D8 |
| `apps/calendar/app/_components/show-block.tsx`, `app/day/[date]/page.tsx`, `packages/ui/src/components/{combobox,select}.tsx`, `app/globals.css` | where the Step 8 fixes would land (F1–F3, F6), only if marked |
| `apps/api/app/routers/shows.py`, `app/sample_data.py` | read-only: the pinned window the plan relies on; not edited |
| `docs/dev/alpha-build-plan.md`, `docs/dev/notes.md`, `docs/arch/arch-initial.md`, `docs/references/nextjs-style-guide.md`, `apps/calendar/AGENTS.md`, `AGENTS.md`, `docs/dev/conventions.md` | Departure 1 and 9 |

## Verification

1. **Unit tests, offline:** `pnpm --filter calendar test`: needs no browser, API or network; all green (the ratchet is written, and `clock.test.ts` does not depend on K1).
2. **The suite:** `E2E_CHROMIUM_PATH=/opt/pw-browsers/chromium make e2e` here (cloud); plain `make e2e` on a laptop after `pnpm exec playwright install chromium`. Then the same with `E2E_ARGS="--repeat-each=3"`: green. **Three tests stay red until Ari fills the gaps** (J1's Today-row assertion for K1, the keyboard focus test for K2, the reflow test for K3); **every other test is green**, including every scan and the whole baseline. Before the handoff the build **checks each gap's code from this plan in a throwaway `git worktree`** (filled in there, never on the branch): the three tests go green, as B5 did (B5 fact 15).
3. **No orphans:** after a run, nothing answers on 8101, 8102 or 3100 (`for p in 8101 8102 3100; do curl -s -o /dev/null -m 2 -w "$p:%{http_code} " http://127.0.0.1:$p/; done` prints `000` three times; `ss` is not installed in the sandbox). Stop any stray server by PID, never `pkill -f` (`notes.md`).
4. **Mutations** (each: break one thing, run the named test, see red, restore). The conventions' `M` form; the table is recorded in the log. **B6-M4, M5, M6 and M9 depend on a test that an open gap already reddens, so they prove nothing on the branch:** the build runs them in the same throwaway worktree with the gaps filled and records the result; M1–M3, M7, M8 and M10 run on the branch.

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
   | B6-M11 | `setOptimistic(next)` removed from the filter header (added in code review round 1) | J8 |

5. **`make check`** red only through the three open gaps' tests (K1, K2, K3), with `e2e` included. The CI job green on the PR is **not verifiable from a cloud session** before the push: the handoff says so.
6. **Not verified here:** Node 24 (CI) and Ari's laptop (this sandbox is Node 22.22.0); `playwright install --with-deps chromium` on the CI runner; the browser build Playwright expects (the sandbox ran an older one, fact 2).
7. **Ari's manual pass** (about 45 minutes; recorded in the Implementation log as a table: screen, tool, what happened, finding ID).
   - *Keyboard only, no mouse, Chrome:* `/` from the address bar: Tab through the header and the filters; open Venues with the keyboard, pick one with Enter, remove the chip with the keyboard, Esc, Tab out; the Month select by keyboard; reach a show's time link and press Enter; Back. Note any trap, any moment you cannot see where focus is, any control you cannot reach.
   - *Screen reader (VoiceOver on macOS or NVDA on Windows), on `/`, `/day/2026-10-07`, `/venue/3`, `/artist/9`, `/show/2`, a 404:* the landmarks and heading list; the links list (does "9:00 PM – 11:30 PM, show details" make sense out of context?); each show block's read-out; the filters' announcements ("Venues, combobox …", the chips' "Remove …" buttons); whether **Updating…** is announced after a pick, whether **No matches found** is announced, what is read while the page is loading (F5); whether picking a filter without a submit button is surprising (3.2.2).
   - *Zoom and spacing:* 200% browser zoom on `/`; apply a text-spacing override and look for clipped or overlapping text (1.4.4, 1.4.12).
8. **Ari's gate:** mark each of F1–F4 and F6 (and anything new) must-fix, should-fix or nit before round 2. F5's markup is D8; its announcement question is in the manual pass.

## Not doing in B6

Visual snapshots; Firefox, WebKit or a device matrix; dark mode (D7); the unfiltered empty message (B5-K3 owns it); API-down journeys beyond the one scan; load or speed tests; scanning `apps/admin` (no role, `arch-initial.md` §7); fixing any finding before Ari marks it (D9; D8's skeleton markup is the one exception, its approval being the mark); any change to the API, `schemas.py`, the fixtures or `lib/api-types.ts`.

## Follow-ups for other milestones

- **A1b:** the e2e stack depends on a deterministic data source. When the routers move onto Postgres, the e2e job needs a Postgres service **and** a seed that loads the same shows (A1b's open "keep a sample-data source" item now has this consumer). And the API's clock becomes real then: the pin must reach it (a Python-side clock the tests can fix), and the **real date cliff the build plan feared arrives at that point**, not now (P1).
- **H milestones:** the hosted phase may want the same suite against a deployed preview; the harness takes `E2E_BASE_URL`-style configuration but B6 builds for the local stack only.
- **Dark mode:** if it is ever added, add it to the scan matrix.
- **Other unlabelled controls:** B5's follow-up (the remaining Base UI wrappers) is covered by the scan and the popup-state scans.
- **Throttled and offline states, API-down detail pages:** not built; the proxy's `__fail` mode makes them cheap when wanted.

## Plan review

### Round 1 — Claude Opus 5.5, October 19, 2026

**Scope:** the plan as committed in `af48c6d` on `claude/sharp-euler-uoi339`; no code yet. **Read:** `AGENTS.md` ("[fill-in] tasks", "Implementation plans", "Cloud sessions", Conventions),
`apps/calendar/AGENTS.md`, `docs/references/nextjs-style-guide.md` (Testing, Anti-patterns), `alpha-build-plan.md` §6 B6
(strategy, "Standing rule: the test clock", "Known date cliff"), `notes.md` ("The home page's window moves with the
clock…"), `conventions.md` (scopes, forms), and the code the plan relies on: `apps/api/app/routers/shows.py`,
`app/sample_data.py`, `apps/calendar/{app/page.tsx,app/layout.tsx,app/not-found.tsx}`,
`app/_components/{calendar-skeleton,filter-header,calendar-grid,calendar-results,show-block}.tsx`,
`app/venue/[id]/page.tsx`, `app/day/[date]/page.tsx`, `lib/{dates,api}.ts`, `vitest.config.ts`, `tsconfig.json`,
`packages/eslint-config/{base,next}.js`, `turbo.json`, `Makefile`, `.github/workflows/ci.yml`, `.gitignore`,
`scripts/cloud-setup.sh`, and `lib/fixtures/{shows,venues,artists}.json`.

**Run (no throwaway `git worktree` was needed; nothing in the repo was written, and `git status` shows only this file):**
- `TestClient(app)` with a dummy `DATABASE_URL`: `/shows` → `2026-09-28 2026-10-25 25`; `/health` 200 with no database;
  `venue_id=2&artist_id=1` → 0 shows; `/venues/9999` → 404. CONFIRMED S1 (the window is pinned to `data.START`), S4 and
  fact 3.
- Fixtures read with Python: 2026-10-07 is a Wednesday holding shows 8, 22, 23, 24, 25 (25 at 01:00, Midway); venue 1
  has 8 shows; Charlie Parr (artist 1) plays only venues 1 and 3; Beasthead is artist 9. CONFIRMED the plan's
  expected-value table. Also found: show 22 has a start time (finding 7).
- The Temporal polyfill (`@js-temporal/polyfill` 0.5.1, `dist/index.esm.js`) reads `Date.now()` for `Temporal.Now`.
  This supports D2's `Date.now`-only preload. CONFIRMED by reading the source.
- `pnpm test` in `apps/calendar`: 21 files, 337 tests, green. CONFIRMED.
- `eslint --max-warnings 0 --stdin --stdin-filename e2e/support/{fake-now,delay-proxy}.mjs` in `apps/calendar` on the
  plan's preload text and a minimal `node:http` proxy: both fail (finding 3). CONFIRMED.
- In a scratchpad directory outside the repo (deleted afterwards): `@playwright/test@1.64.1`, `@axe-core/playwright@4.14.0`
  and `vitest@5` installed. Playwright's default `testMatch` is `**/*.@(spec|test).?(c|m)[jt]s?(x)`
  (`playwright/lib/common/index.js:599`). With `testDir: "e2e"` and a Vitest file at `e2e/support/a.test.ts`,
  `playwright test --list` fails to load it and lists 0 tests (finding 2). CONFIRMED. A value import of `expect` from
  `@playwright/test` inside a Vitest test runs fine (so `a11y-baseline.ts` may import Playwright types without breaking
  `pnpm test`). CONFIRMED. `webServer` teardown kills the process group (`process.kill(-pid, signal)`), so `uv run`'s
  child is reaped when `gracefulShutdown` is set. CONFIRMED by reading the source; the plan's "no listener remains" check
  still stands.

**Not run:** a production `next build`/`next start` with the preload, the delay proxy, or axe. The plan's facts 4–10 are
taken as recorded. The plan says itself that the build re-derives them.

**Counts:** 1 blocker, 6 should-fix, 11 nit. **Verdict: proceed after fixes.** The design is sound and well evidenced: the
real API on sample data, the server-side clock pin, the delay proxy, the ratchet and the two-round process. The blocker
is about sequencing, not design. With K1 open, every axe-backed test throws, so most of what Steps 3, 5 and 6 commit
cannot be verified by the build, and the Verification section's "every other test is green" is false.

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | blocker | **K1 is open during the whole build, and every scan depends on it.** `compareToBaseline` throws `NotImplementedError` from Step 3 on, so `a11y-home`, `a11y-screens`, `a11y-popups` and `focus-indicator` (which ratchets F3 and F6) are all red for the rest of round 1. The plan does not account for this. Step 3.3 ("the first run is red with F1 as *added*; commit the baseline entry") cannot happen: the run is red from the throw, not with F1 as *added*. The baseline rows for F1 on the other pages, F2, F3 and F6 (Steps 5.3, 5.4, 6.3) cannot be checked through the ratchet. "Each step ends green" (Implementation steps preamble) cannot hold after Step 3. Verification 2 and 5 say only K2's and K3's tests stay red. Mutations M5–M8 are already red before the break, so they prove nothing until K1–K3 are filled | Plan: TODO(Ari) gaps K1 "*Check:* … red until filled"; Step 3.2–3.3; Step 5.3–5.4; Step 6.3; Verification 1, 2, 4, 5. CONFIRMED by reading | The build either fills K1 to get its numbers (breaking the [fill-in] rule) or commits baseline rows nobody has run through the comparison. Then Ari fills K1 and gets reds that are not about his line. The code reviewer cannot run the scans either | **Fixed.** The ratchet comparison is [written] with its unit tests ("The ratchet", Step 3, D10), so every scan, baseline row and mutation runs without a gap. The `TODO(Ari)` gaps are now K1 the clock pin (new, in Step 2: finding 18's suggestion), K2 the focus predicate and K3 the reflow predicate. Each reddens only its own test (J1's Today row; the keyboard test; the reflow test), stated in the gaps section, the steps preamble and Verification 1, 2 and 5. Mutations M4, M5, M6 and M9 depend on those tests, so Verification 4 has the build run them (and each gap's code) in a throwaway worktree with the gaps filled. **This changes the plan's gap layout, so Ari may want a second plan-review round.** |
| 2 | should-fix | **Playwright will collect the Vitest helpers.** The layout puts `clock.test.ts` and `a11y-baseline.test.ts` under `e2e/support/`, and the config line lists no `testMatch`. Playwright's default matches `*.test.ts` as well as `*.spec.ts`. Fact 11 checked only the other direction (Vitest ignores specs). The config needs `testMatch: "**/*.spec.ts"` (or `testIgnore: "**/support/**"`), stated in the plan and in Step 1 | Default `testMatch` `**/*.@(spec\|test).?(c\|m)[jt]s?(x)` (`playwright/lib/common/index.js:599`). Scratch run: `playwright test --list` with `e2e/support/a.test.ts` importing `vitest` → load error, "Total: 0 tests in 0 files". CONFIRMED | Step 2 adds `clock.test.ts`, and the whole e2e suite stops loading | **Fixed.** The config sets `testMatch: "**/*.spec.ts"` (layout, "Specs are `*.spec.ts`…" paragraph, Step 1 item 2) and fact 11 records the Playwright default. |
| 3 | should-fix | **The two `.mjs` support files fail `pnpm lint`. Fact 11 names only `playwright.config.ts`.** The shared ESLint config gives `.mjs` files `globals.serviceworker` only, so `process` is `no-undef`. `fake-now.mjs` also trips `turbo/no-undeclared-env-vars`. Both are warnings, and warnings fail under `--max-warnings 0`. Fix: `import process from "node:process"` in each file, or a scoped `globals.node` block for `e2e/**/*.mjs` in `apps/calendar/eslint.config.js`. Declare the variables in `turbo.json` under `globalPassThroughEnv`, which `eslint-plugin-turbo` 2.7.1 reads; an entry under `build.env` would change the build's cache hash for a variable the build never reads | `eslint --max-warnings 0 --stdin --stdin-filename e2e/support/fake-now.mjs` → "E2E_FROZEN_NOW is not listed…", "'process' is not defined (no-undef)", exit 1. The same for a `delay-proxy.mjs` reading `process.argv`. CONFIRMED | `make check` and the CI `js` job go red on Step 1 or Step 2's files | **Fixed.** "The stack" gains a **Lint** paragraph: `globalPassThroughEnv` in `turbo.json` for the variables, a scoped `globals.node` block in `apps/calendar/eslint.config.js` for `e2e/**/*.mjs`; fact 11, Step 1 (item 2 and the done-condition: zero lint warnings) and Critical files updated. |
| 4 | should-fix | **The screenshot-diff measurement (Step 6.3, fact 8) does not say how the PNG is decoded.** `locator.screenshot()` returns PNG bytes, and Node cannot read pixels from them without a decoder. `sharp` is in the store only as Next's optional dependency, and pnpm's strict layout does not expose it to `apps/calendar`. Either decode in the browser (draw the base64 PNG on a canvas inside `page.evaluate`, no dependency) or add a decoder such as `pngjs` as a third dev dependency. Approval on October 17 covered two dependencies, so a third needs Ari's yes | `ls node_modules/.pnpm \| grep -E "pngjs\|sharp"` → `sharp@0.35.3` only. Plan, Critical files: "two dev dependencies". CONFIRMED that no decoder is declared; PLAUSIBLE that the prototype decoded in the browser | The build adds an unapproved dependency, or stalls on Step 6.3 | **Fixed.** Step 6.3 says the PNGs are decoded in the browser (base64 onto a canvas in `page.evaluate`, `getImageData`), which is what the prototype did; no third dependency. |
| 5 | should-fix | **D8 fixes F5 in round 1, which contradicts D9 and "Not doing".** Step 5.1 changes `calendar-skeleton.tsx` before Ari marks anything. "Not doing" says "fixing any finding before Ari marks it (D9)", and Verification 8 still asks Ari to mark F5. If D8 is approved, the approval is the mark. Say so in D8 and D9, record F5 as "fixed in round 1 by D8" in the findings table, and drop it from Verification 8's list | Plan: D8; D9; Step 5.1; "Not doing in B6"; Verification 8. CONFIRMED by reading | Ari is asked to mark a finding that is already fixed, and code review sees a production change the plan says it will not make | **Fixed.** D8 says approving it is the mark and the markup is changed in round 1; F5 is recorded as "markup fixed by D8"; D9, "Not doing" and Verification 8 carry the one exception. |
| 6 | should-fix | **The WCAG 2.2 AA matrix misfiles two criteria as N/A and leaves out four.** 3.2.1 On Focus (A) applies to every focusable component; Step 6.2's keyboard journey can confirm that focus alone never navigates. 2.5.3 Label in Name (A) applies to the labelled filters and the time links ("9:00 PM – 11:30 PM, show details" passes because the visible text comes first). axe's rule for it is experimental and not in the plan's tags, so it is a by-inspection row. Missing: 1.3.2 Meaningful sequence, 1.3.3 Sensory characteristics, 1.4.5 Images of text (posters on the show page carry text, and the same information is in HTML), 3.1.2 Language of parts. 2.5.2 Pointer cancellation is better as "by inspection" (Base UI popups open on pointer-down, like a native select) than N/A | Plan: WCAG matrix, the N/A row ("2.5.1–2.5.4, 3.2.1"). CONFIRMED that the rows are missing; the applicability is reasoned against WCAG 2.2 (PLAUSIBLE) | The matrix claims every applicable criterion. The manual pass and the findings table inherit the gaps, and an AA sign-off rests on an incomplete list | **Fixed.** The matrix gains 1.3.2, 1.3.3, 1.4.5, 2.5.2, 2.5.3, 3.1.2 and 3.2.1 with how each is checked (the last by the keyboard journey); the N/A row no longer lists 2.5.2, 2.5.3 or 3.2.1. |
| 7 | should-fix | **`make check` in a cloud session needs `E2E_CHROMIUM_PATH`, and nothing sets it.** D4 adds `e2e` to `make check`, which is the done gate for every later cloud session, on either track. The sandbox sets `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers` but not the new variable, and Playwright 1.64 wants build 1248, which is not there. Only a doc line is planned (Departure 9). Add `scripts/cloud-setup.sh` to Critical files and have it export the variable, or have the config fall back to `/opt/pw-browsers/chromium` when `CLAUDE_CODE_REMOTE=true` | `env` in this sandbox: `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`, `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`, no `E2E_*`. `/opt/pw-browsers/chromium` → `chromium-1194/chrome-linux/chrome`. CONFIRMED. That the session hook can export variables is PLAUSIBLE | Every cloud `make check` after B6 merges fails on a missing browser, for work that never touched the frontend | **Fixed.** `scripts/cloud-setup.sh` exports `E2E_CHROMIUM_PATH` through `CLAUDE_ENV_FILE` (the mechanism it already uses for `PATH`), in "The stack" (Cloud sessions), Step 1, Critical files and Departure 9; the build verifies it from a fresh shell. |
| 8 | nit | **"Show, timed and untimed: `/show/2`, `/show/22`" — show 22 is timed** (18:00, no end time). The untimed shows are 3, 9 and 19, which render the "Time not listed · Details" branch. Use `/show/3` (or `/show/9`) for the untimed screen; keep 22 if "start but no end" is wanted as a third case | `shows.json`: id 22 `start_time "18:00:00"`; ids 3, 9, 19 `start_time null`. CONFIRMED | The scan never sees the untimed rendering it claims to cover | **Fixed.** The screen list uses `/show/2`, `/show/3` (untimed) and `/show/22` (start time, no end). |
| 9 | nit | **J6a and J6b name links that appear more than once on `/`.** "Zhora Darling" is a venue heading in every date row where it has a show (6 shows), and "Beasthead" plays shows 2 and 8. A bare `getByRole("link", { name })` is a strict-mode error. Scope each one, for example to the Oct 7 row or show 2's `<article>`, and say which | Fixture counts above. CONFIRMED | The test fails with a strict-mode violation, or someone adds `.first()` without saying why | **Fixed.** J6a is scoped to the Today row and J6b to show 2's article (located by its time link); each says why. |
| 10 | nit | **The status and `aria-busy` assertions have two traps.** (a) The filter header always renders an empty `role="status"` (`filter-header.tsx:151`), so once D8 adds one to the skeleton, J9's "the status is gone" cannot be `getByRole("status")` disappearing. Assert on the text "Loading shows" instead. (b) `aria-busy={isPending}` renders `"false"`, not no attribute (`:98`), so J8's "clear" is `toHaveAttribute("aria-busy", "false")` | `filter-header.tsx:98`, `:151`. CONFIRMED by reading | J9 times out waiting for a status that never leaves; J8 asserts that an attribute is absent when it is never removed | **Fixed.** J9 asserts on the text "Loading shows", not a status role going away; J8 asserts `aria-busy` becomes the string `"false"` and the always-present status element empties. |
| 11 | nit | **D8 overstates what the status paragraph does for screen readers.** A live region that is already in the first HTML with its text is generally not announced. Removing it is not announced either. So "gives screen-reader users a loading state" mostly means "readable if the user goes looking". The fix is still worth making as a test handle. Say what it does and does not do, and keep F5's screen-reader check in the manual pass. `aria-busy` on the results region is the other common pattern | ARIA live-region behaviour (PLAUSIBLE; not run in a screen reader) | The findings table records F5 as resolved when the manual pass may still find silence | **Fixed.** D8 now says what the paragraph does (a locator, and discoverable on browsing) and does not promise (an announcement); F5's announcement question stays in the manual pass; `aria-busy` is named as the other pattern. |
| 12 | nit | **K2's lesson, predicate and coverage.** (a) "Centre not covered" is *stricter* than 2.4.11's "not entirely hidden": it is a sufficient check, not the criterion. Say so in the Lesson, so the gap does not teach the wrong reading. (b) A wrapped inline link (the artist links are plain inline `<a>`) has a bounding-box centre that can fall between its line boxes, so `elementFromPoint` returns the parent and reports a false "obscured". Using `el.getClientRects()[0]` avoids this. (c) Step 6.2 tabs only `/`, but `/venue/[id]` renders the same `CalendarGrid` with the same sticky `h2` (`calendar-grid.tsx:36`). Add `/venue/1`, or say why one page is enough | Plan: K2; Step 6.2; `calendar-grid.tsx:36`; `app/venue/[id]/page.tsx`. (a) and (c) CONFIRMED by reading; (b) PLAUSIBLE (the plan says the strict predicate is unverified) | Ari types a check whose meaning the lesson misstates, and a false red at 375px sends him debugging the wrong line | **Fixed.** K2's lesson says the centre test is stricter than 2.4.11 and who decides if it must loosen; the code uses `getClientRects()[0] ?? getBoundingClientRect()` (marked PLAUSIBLE, verified in the build's worktree); Step 6.2 and K2's Check tab `/venue/1` as well as `/`. |
| 13 | nit | **IDs and cross-references.** `B6-F<n>` reuses the conventions' `F` form ("a failure found in an eval") with a new meaning, and the `S` rows reuse `S` ("a sampling or design lever"). Departure 9 adds the scope row but not a forms update, and code and baseline rows will cite `B6-F1`. Two references inside the plan point at the wrong thing: S5's "S1 of this plan's steps" means Step 1, and S13's "Policy in S3 below" means "The ratchet" section (S3 is dark mode) | `conventions.md` Forms table; plan S5 and S13 rows. CONFIRMED | A reader looks up `B6-F2` as an eval failure, or follows S3 to dark mode | **Fixed.** The scrutiny rows are relabelled `P1–P17` (a local label, so they no longer reuse the `S` form), the two wrong cross-references are corrected ("Step 1 of this plan", "The ratchet"), and Departure 9 widens `conventions.md`'s `F` form to cover findings from a scan or check (`B6-F2`) and adds the `B6` scope row. The reviewer's own round keeps the original `S` labels, as earlier rounds are not edited. |
| 14 | nit | **J6c reads the expected title off the page "and then pins" it.** That breaks ground rule 3 (expected values are not read from the code under test). B4-D7 defines the title format. Write the expected title from that format with the source in a comment | Plan: J6c; ground rule 3. CONFIRMED by reading | The test pins whatever the page happens to say, wrong or not | **Fixed.** J6c's expected title is written from B4-D7's format with the source cited, and a mismatch with the page is investigated, never copied. |
| 15 | nit | **Waiting on `networkidle`.** Fact 12 says most of the sweep's time is `networkidle` waits. Playwright discourages it, and production `<Link>` prefetching keeps the network busy. Ground rule 7 should say what to wait for before a scan: the streamed content, such as the expected `<article>` count or the h1. Waiting on the content is also what makes the scan see the calendar and not the skeleton | Plan: fact 12; ground rule 7. PLAUSIBLE | Slow scans that fail intermittently, or a scan of the skeleton | **Fixed.** Ground rule 7 forbids `networkidle` and says to wait on the h1 and the expected article count before any assertion or scan (which also keeps a scan off the skeleton); fact 12 notes the prototype used `networkidle`. |
| 16 | nit | **Departure 1 rewrites existing paragraphs** in `alpha-build-plan.md` and `notes.md`. `AGENTS.md` ("Parallel tracks") asks for edits to those two files to be "small and append-only" to avoid conflicts with the A track. The paragraphs are B6's own, so an in-place rewrite is defensible. Keep it to those paragraphs, or append a dated correction under them | `AGENTS.md` "Parallel tracks"; plan Departure 1. CONFIRMED by reading | A merge conflict with a concurrent A-track branch | **Fixed.** Departure 1 says the `alpha-build-plan.md` and `notes.md` edits are in place but confined to B6's own paragraphs and section. |
| 17 | nit | **`E2E_BASE_URL` is declared but nothing reads it.** Follow-ups says B6 builds for the local stack only. Drop it until the H milestones need it | Plan: "The stack", last paragraph; Follow-ups ("H milestones"). CONFIRMED by reading | A configuration knob that does nothing and suggests a feature that is not there | **Fixed.** `E2E_BASE_URL` is dropped from the declared variables and the lint paragraph. |
| 18 | nit | **Gap choice: K3 is weak, as D10 says. A stronger lesson sits in the clock pin.** "`page.clock` cannot reach a Server Component, so the pin goes on the Next server, and only `Date.now`" is the RSC server/browser split this learning project is about. The two `fake-now.mjs` lines (or the `webServer` `env` that scopes `NODE_OPTIONS` to the Next process) would make a better gap than K3's `scrollWidth` comparison. Check: J1's Today row, and M9 | Plan: D2, D10, K3; S1 ("`page.clock` is browser-side"). Judgement | A gap that teaches a measurement idiom where one could teach the architecture | **Fixed.** The clock pin is now K1 (Step 2, D10): `Date.now = () => FROZEN` in `fake-now.mjs`, with the server/browser lesson. Its placeholder is a missing line, not a `throw`, so an open gap reddens only J1 (reasoned in the gap). K3 stays as the weakest gap, flagged in D10 for Ari to drop. |

Rejected: none. All 18 findings were accepted; the blocker (finding 1) was resolved by changing which lines are `TODO(Ari)` gaps, which is a plan change rather than a rejection.

## Implementation log

### Round 1 — Step 1, the harness and one green test (Claude Sonnet 5.5, October 19, 2026)

**Paused here on purpose (D11).** Ari runs the one test himself before Step 2 starts. No second-model review yet: it runs once, after all implementation (D11).

**Scope:** working tree on `claude/sharp-euler-uoi339` against base `2efabbd`; committed and pushed at the pause so Ari can run it (a cloud session's work only reaches him through the branch). Files:

| File | Change |
|---|---|
| `apps/calendar/e2e/home.spec.ts` | new: J1's first half, written **first** (red: no browser path, no stack) |
| `apps/calendar/e2e/support/{stack.ts,delay-proxy.mjs,test.ts}` | new: ports, the pass-through proxy (controls come in Step 4), the shared `test`/`expect` |
| `apps/calendar/playwright.config.ts` | new: `testMatch`, one worker, no retries, three `webServer` entries, `E2E_CHROMIUM_PATH` |
| `apps/calendar/package.json`, `pnpm-lock.yaml` | `@playwright/test` 1.64.1 (the lockfile's `next@16.3.0(…)` key gains the optional-peer suffix, plan fact 1) |
| `apps/calendar/eslint.config.js` | a scoped `process` global for `e2e/**/*.mjs` |
| `turbo.json` | `globalPassThroughEnv`: `E2E_CHROMIUM_PATH`, `CI` |
| `Makefile` | `make e2e`, `E2E_ARGS`, and `e2e` added to `make check` (D4) |
| `.github/workflows/ci.yml` | the `e2e` job, carrying `--repeat-each=3` for this commit |
| `.gitignore` | `playwright-report/`, `test-results/` |
| `scripts/cloud-setup.sh` | exports `E2E_CHROMIUM_PATH` through `CLAUDE_ENV_FILE` |
| this plan | Status, D11 |

**Departures from the plan**
1. **ESLint's `.mjs` block declares `process` inline** (`globals: { process: "readonly" }`), not `globals.node`: the `globals` package is a dependency of `packages/eslint-config`, not of `apps/calendar`, and pnpm's strict layout would not resolve it. A direct dependency would be a third unapproved one. The block is correct for what the two files use today; widen it if a later file needs more.
2. **`CI` is declared in `globalPassThroughEnv` too.** The config reads it to choose the reporter and `eslint-plugin-turbo` flagged it (`--max-warnings 0`).
3. **`make e2e` passes `API_BASE_URL=http://127.0.0.1:8102` to the build.** Nothing is fetched at build time, but the variable has to exist; the plan did not say.
4. **The CI job caches the browser with `actions/cache@v4`**, which the repo's workflows did not use before. Its version is the one I know; the job has not run (see Not verified).
5. **The proxy's readiness URL is `/health`, forwarded to the API,** so the proxy is "ready" only when the API is. That is what the order of the `webServer` entries needs anyway.

**`TODO(Ari)` gaps:** none open yet. K1 arrives in Step 2, K2 and K3 in Step 6.

**Verification** (Node 22.22.0, this sandbox)
- Red first: with only a bare config, the test failed with `Executable doesn't exist at /opt/pw-browsers/chromium_headless_shell-1248/…` (no browser path, no stack).
- `E2E_CHROMIUM_PATH=/opt/pw-browsers/chromium make e2e`: **1 passed** (0.6–1.0 s for the test; ~39 s with the build). uvicorn shut down gracefully ("Application shutdown complete").
- `make e2e E2E_ARGS="--repeat-each=3"`: **3 passed** (0.58, 0.68, 0.66 s).
- After each run, `curl` to 8101, 8102 and 3100 gets no answer (`000`) and `ps` shows no uvicorn, next-server or proxy process: **no orphans**.
- `pnpm turbo run lint check-types test`: 7 of 7 tasks successful, **zero lint warnings**, 337 Vitest tests.
- **`make check`: exit 0.** ruff clean; pytest 669 passed, 15 skipped (the known cloud skips); Vitest 337 passed; contract current; e2e 1 passed.

**Not verified:** the CI job (a cloud session cannot run it before the push; its YAML parses and its steps mirror the local commands); Node 24 and Ari's laptop; `playwright install --with-deps chromium` and the `ms-playwright` cache path on the runner; the `cloud-setup.sh` export (the session hook had already run, so it takes effect at the next session start: check `echo $E2E_CHROMIUM_PATH` in a fresh cloud session); `gracefulShutdown` on a Mac or Windows laptop.

**Where to look hardest:** `playwright.config.ts` is the file to read, since the rest of the milestone stands on it: the order and readiness of the three servers, `reuseExistingServer: false`, and the hand-off of `API_BASE_URL`. Second, the CI job, which nothing here has exercised.

**How to run it yourself (D11)**

```
git fetch origin claude/sharp-euler-uoi339 && git checkout claude/sharp-euler-uoi339
pnpm install
(cd apps/api && uv sync)
pnpm --filter calendar exec playwright install chromium     # one-time: Playwright's own browser
make e2e                                                     # builds, starts the 3 servers, runs the test, stops them
```

To get a feel for it (each is the same command with `E2E_ARGS`):

| Try | Command | What you see |
|---|---|---|
| Watch the browser | `make e2e E2E_ARGS="--headed"` | A real Chromium window opening the page |
| UI mode | `make e2e E2E_ARGS="--ui"` | Playwright's inspector: every step, a DOM snapshot before and after it, a timeline |
| Break it on purpose | change `"Live music"` to `"Live musicc"` in `e2e/home.spec.ts`, run `make e2e` | A failure that names the locator, what it waited for, and the page state; then `pnpm --filter calendar exec playwright show-trace test-results/<test folder>/trace.zip` replays it |
| Step through | `make e2e E2E_ARGS="--debug"` | The Playwright Inspector, one action at a time |

(Locally the reporter is `list`; the HTML report is for CI.) Then tell the next session to continue the build from Step 2.

### Round 2 — Steps 2–7, the rest of the build (Claude Sonnet 5.5, October 19–20, 2026)

Step 1 was round 1 (Ari ran it and said to continue). This round is the rest, and **the second-model code review covers Steps 1–7 together** (D11). Step 8, the fix round, waits for Ari's marks on findings F1–F7.

**Scope:** `git diff 2efabbd` (the last plan commit) on `claude/sharp-euler-uoi339`: 50 files, about 2,080 insertions. Commits `83d63b1` (Step 1) to `26a5a4f` (docs and F7). Files:

| Area | Files |
|---|---|
| Harness | `apps/calendar/playwright.config.ts`; `e2e/support/{stack.ts,test.ts,delay-proxy.mjs,fake-now.mjs,clock.ts,screens.ts}`; `Makefile` (`make e2e`, in `make check`); `.github/workflows/ci.yml` (`e2e` job); `turbo.json`; `apps/calendar/eslint.config.js`; `.gitignore`; `scripts/cloud-setup.sh` |
| Journeys (J1–J9) | `e2e/{home,filter-venue,filter-empty,filter-history,day-view,venue-page,artist-page,show-page,not-found,filter-busy,skeleton}.spec.ts` |
| Accessibility | `e2e/{a11y-screens,a11y-popups,focus-indicator,keyboard,reflow}.spec.ts`; `e2e/support/{a11y.ts,a11y-baseline.ts,focus.ts,reflow.ts,contrast.ts}` |
| Unit tests (Vitest) | `e2e/support/{clock,a11y-baseline,contrast}.test.ts`; `app/_components/calendar-skeleton.test.tsx` |
| Production code | `app/_components/calendar-skeleton.tsx` (D8: a hidden "Loading shows" status), nothing else |
| Docs | the build plan's B6 section, `notes.md`, `arch-initial.md`, `nextjs-style-guide.md`, `conventions.md`, `README.md`, `AGENTS.md`, `apps/calendar/AGENTS.md` |

**Departures from the plan** (each with its reason)
1. **Today row found by its badge, not `getByRole("listitem", { current: "date" })`.** Playwright has no `current` option (Testing Library does; `next build` rejected it as a type error). The row is found by the "Today" text and `aria-current="date"` is asserted on it.
2. **J6a is scoped to the Oct 7 row by its date heading, not the Today row,** so it does not depend on the pin (K1). Otherwise an open K1 would redden J6a as well.
3. **Added: a request-settling fixture and a hermetic browser (`e2e/support/test.ts`).** Ari's first run showed Next logging `The destination stream closed early` (link prefetches still streaming when the browser closed). The `page` fixture now resets the proxy and waits for in-flight requests before closing, and refuses outside requests (the sample data's poster and photo URLs point at example.com; images are answered with a 1x1 PNG). Before: 1 occurrence in 30 runs here; after: 0 in 285. Not in the plan.
4. **`a11y-home.spec.ts` (Step 3) was removed** when Step 5's every-screen spec subsumed it. The shared screen list is `e2e/support/screens.ts`, used by the scan and the reflow spec.
5. **The strict K2 predicate found a real stop** (finding F7), so `keyboard.spec.ts` does not assert `hidden === []` but holds the hidden stops to the ratchet baseline (a custom `b6-focus-obscured` finding). With K2 filled strictly as written, the test is green with F7's row; a sticky-heading regression would show as added. The plan's gap text says so.
6. **Painted-focus ratios use the page background, not the before/after pair.** The prototype compared the changed pixel with what it replaced (the Month select's border: 229 to 181, 1.63:1); the build compares it with the page background (2.58:1). So the numbers differ from the plan's fact 8. Artist link 1.76 (the plan's 1.54 was the nav link; the darkest changed pixel on the artist link is stronger).
7. **The measurement has self-tests** (`focus-indicator.spec.ts`, first block): a 3px black outline reads about 21:1, a control with no focus style reads nothing, a pale grey ring about 1.6:1, a known border its known ratio. Not in the plan; the method deserves proof before its numbers are trusted.
8. **35 tests are red while the gaps are open, not three.** K3's function is called by 30 reflow tests (15 screens times 2 widths), K2's by 4 keyboard tests, K1's by 1. The plan said "the reflow test" in the singular.
9. **All ten mutations ran in the throwaway worktree with the gaps filled,** not on the branch, so the branch was never edited to break it (the plan had M1–M3, M7, M8 and M10 on the branch). M8 was also run on the branch during Step 3.
10. **The popup scans run at 1280 only** (the plan said "popup states"); the error screen is scanned at both widths.
11. **Docs:** the `F` form widened in `conventions.md`; `README.md` gained a `make e2e` line (not listed in Departure 9).
12. *(Added in code review round 1, which found it missing.)* `react-hooks/rules-of-hooks` is switched off for `e2e/**/*.ts` in `eslint.config.js`: the rule takes Playwright's fixture callback `use` for React's `use()` hook (also in `notes.md`).

**`TODO(Ari)` gaps: all three open** (scaffold only; none was filled). Each reddens only its own tests.

| Gap | Where | Lesson | Command |
|---|---|---|---|
| K1 | [`e2e/support/fake-now.mjs:32`](../../apps/calendar/e2e/support/fake-now.mjs) | Server Components run on the Next server, so the browser's clock tools cannot reach "today"; patch `Date.now` and only that, as a `NODE_OPTIONS` preload | `make e2e E2E_ARGS="e2e/home.spec.ts"` (1 test, `the Today row is the pinned Wednesday`) |
| K2 | [`e2e/support/focus.ts:39`](../../apps/calendar/e2e/support/focus.ts) | WCAG 2.4.11: ask the browser what is on top at the focused control's centre; `toBeVisible()` ignores overlap | `make e2e E2E_ARGS='e2e/keyboard.spec.ts -g sticky'` (4 tests) |
| K3 | [`e2e/support/reflow.ts:26`](../../apps/calendar/e2e/support/reflow.ts) | WCAG 1.4.10: measure the document (`documentElement`), not `body` and not the scrollers that scroll on purpose | `make e2e E2E_ARGS="e2e/reflow.spec.ts"` (30 tests) |

**Verification** (Node 22.22.0, this sandbox; Chromium via `E2E_CHROMIUM_PATH=/opt/pw-browsers/chromium`)
- **`make check`** (exit 2, **red only through the three gaps' tests**): ruff clean; mypy and pytest 669 passed, 15 skipped (the known cloud skips); Vitest 351 passed (25 files; +14 over B5: the clock guard, the ratchet, the contrast arithmetic, the skeleton); contract current; e2e **60 passed, 35 failed** (1 K1 + 4 K2 + 30 K3, every failure `TODO(Ari)` or the Today row on the real clock).
- **Gaps checked in a throwaway worktree** (the plan's code filled in there, never on the branch): the full suite is **95 of 95 green, and 285 of 285 over `--repeat-each=3`** (6.4 minutes, about 2 minutes per run), `pnpm lint` zero warnings once K1's scaffold-only `eslint-disable` is dropped, no `destination stream closed early` line, no listener left on 8101, 8102 or 3100.
- **Mutations** (each: break one thing in the worktree, build, run the named spec, restore):

  | M | Break | Result |
  |---|---|---|
  | B6-M1 | filter pushes with `replace` | J4 red (1 of 1) |
  | B6-M2 | venue page returns markup instead of `notFound()` | J7 `/venue/9999` red (1 of 4) |
  | B6-M3 | no `<Suspense>` around `CalendarBody` | J9 red |
  | B6-M4 | `aria-current` removed from the Today row | J1's Today test red (1 of 2) |
  | B6-M5 | `min-w-[400px]` in the header | reflow red (30 of 30) |
  | B6-M6 | a fixed 96px bar in the layout | the 4 sticky-heading tests red |
  | B6-M7 | an unlabelled `<button>` on `/` | 6 scans red (`button-name` added) |
  | B6-M8 | delete the `/ @1280` baseline row | the `/` scan red (also on the branch, Step 3) |
  | B6-M9 | start Next without the pin | J1's Today test red |
  | B6-M10 | the chip-remove button loses its `aria-label` | J2 red |
  | B6-M11 | *(added in code review round 1)* `setOptimistic(next)` removed from the filter header | J8 red (J8 was green before it was strengthened) |

**Findings** (Ari marks each must-fix, should-fix or nit before the fix round; severities here are proposals). Measured values are from this build; the baseline holds counts, not ratios.

| ID | Finding | WCAG | Evidence | Proposed | Likely fix |
|---|---|---|---|---|---|
| B6-F1 | Artist links are 18px high (24 needed). `/` 6 elements, `/day/2026-10-07` and `?sort=time` 2 each, `/artist/1` 2, the Month popup shows the same 6; same at 375 | 2.5.8 AA | axe `target-size` | **must-fix** | `inline-block py-1`, the day view's own pattern (B4) |
| B6-F2 | `aria-hidden-focus` (5 elements) while the Venues or Artists popup is open: Base UI marks `header`, `footer` and the page content `aria-hidden` yet focusable elements stay inside. It also hides the page from role queries (and a screen reader) while a multi-select's popup is open after a pick | 4.1.2 A | axe, popup state; the journeys needed Escape | **should-fix**; cause not investigated (a Base UI option, or upstream) | find the Base UI prop (`modal`) or accept and document |
| B6-F3 | Painted focus indicator (*re-measured in code review round 1 with the stricter method*): artist link 1.54, nav link 1.54, date heading link 1.54, Venues combobox 2.05, Month select 1.66, Clear filters link 1.54 (all below 3:1; the first measurement, 1.54 to 2.58, took the strongest changed pixel and is superseded) | 1.4.11 AA | screenshot diff, `focus-indicator.spec.ts` | **must-fix** if Ari reads 1.4.11 as covering focus rings (the W3C Understanding document does) | a darker `--ring` at full opacity; the link outline is the ring colour at 50% alpha |
| B6-F4 | At 375px on `/`, axe cannot decide the contrast of 4 venue links ("partially obscured by another element"). Desktop is clean | 1.4.3 AA | axe `incomplete`; hit-testing finds every in-view venue link topmost at its centre | **nit**: triage by eye | none unless a look finds a real overlap |
| B6-F5 | The loading skeleton had no text | 4.1.3 AA (judgement) | by reading | **markup fixed in round 1 by D8** (its approval is the mark); whether a screen reader announces anything is a manual-pass question | done |
| B6-F6 | Unfocused control borders are 1.26:1 on white (Venues box, Month select) | 1.4.11 AA | screenshot, `focus-indicator.spec.ts` | **should-fix or nit**: depends on whether the label alone identifies the field | a darker `--input` |
| B6-F7 | At 375px, tabbing `/` lands on show 2's time link at the right edge of its venue row **half cut off by the row's scroll container** (link x 297 to 425, row visible to 359; the hit point is the page padding). Not a sticky heading | 2.4.11 AA passes (not entirely hidden), but a half-clipped focus is a defect | the strict K2 predicate in a worktree, then a probe | **should-fix**. **Cause unknown** (*corrected in code review round 1: this row first blamed scroll-snap `mandatory`; the review measured the row's `scrollLeft` at 0 after Tab and the stop still hidden with `snap-proximity` and with no snapping, so snapping is not it*). Leading hypothesis, PLAUSIBLE: Chromium does not scroll an element that is already partly visible (62 of its 128 px show) | To investigate. Candidates: columns narrow enough that a link is never split at 375, or scrolling the focused link fully into view (client code in a Server Component grid). `scroll-padding` and `proximity` snapping are ruled out |

Not findings: reflow passes on all 15 screens at 320 and 375; focus is never entirely hidden and never under a sticky heading on `/` or `/venue/1` at either width; all 15 screens' browser titles match the exact expected text (2.4.2); both 404 pages and the error screen are clean; the muted-on-muted pair (4.35:1 by arithmetic) is not rendered anywhere (the chip is `text-foreground`).

**`incomplete` triage** (the 13 screens that list shows or details, 2 widths; *corrected in code review round 1: the first draft said 13 pages, and the screen list is 15 plus the error screen, which the clean results already cover*): the only incomplete result is F4 above.

**Not verified:** the CI `e2e` job (a cloud session cannot run it before the push; the YAML parses and mirrors the local commands, and `actions/cache@v4` is the version I know); Node 24 and Ari's laptop; `playwright install --with-deps chromium` and the `ms-playwright` cache path on the runner; the `cloud-setup.sh` export from a fresh session (this session set the variable by hand); the headed and UI modes on a laptop; **K1, K2 and K3 as Ari types them** (verified as the plan's code in a worktree, not as typed); the manual keyboard and screen-reader pass (Ari's, Verification 7).

**Where to look hardest**
1. **F7's cause** is a hypothesis; nothing diagnosed it. And F2's cause was not investigated.
2. **The focus-indicator measurement** (`e2e/support/focus.ts`): a diff of two screenshots with animations disabled. The self-tests cover known pages, but the baseline holds counts, so a ring that moves across 3.0 flips a count. Is "strongest changed pixel against the page background" the right reading of 1.4.11 for a ring that anti-aliases?
3. **The `page` fixture** (`test.ts`): the best-effort wait (a `.catch(() => {})` on the poll) and the unconditional proxy reset in it. A test that hangs a request for more than 5 seconds is silently let go.
4. **The stubbed images** make every page's images 1x1: the scans never see a real image's `alt` text rendering or its overflow.
5. **The CI job** has not run.
6. **`next build` type-checks `e2e/`** (notes.md): a type error in a spec now breaks the Vercel build, not only `check-types`.

**Handoff notes for Ari:** mark F1–F7 (and any the review adds); fill K1–K3 (or tell a session to); run the manual pass (Verification 7); the findings gate before sign-off.

## Code review

### Round 1 — Claude Opus 5.5, October 20, 2026

**Scope:** `git diff 2efabbd` on `claude/sharp-euler-uoi339` at `eea430c` (commits `83d63b1` to `eea430c`, 50 files): Implementation log rounds 1 and 2, Steps 1–7. The three open gaps (K1, K2, K3) are not findings.

**Read:** `AGENTS.md` ("[fill-in] tasks", "Implementation plans", "Cloud sessions", Conventions), `apps/calendar/AGENTS.md`, `docs/references/nextjs-style-guide.md` (Testing, Anti-patterns), `docs/dev/conventions.md` (forms, the check command), this plan in full, and every file in the diff. Also read the code the tests rely on: `filter-header.tsx` (`useOptimistic`, `aria-busy`), `calendar-grid.tsx` (the row scroller), `lib/api.ts` (`no-store`), `remote-image.tsx` (plain `<img>`, so the image stub in `test.ts` covers it). **Anti-patterns table:** the only production change is `calendar-skeleton.tsx`, a sync Server Component with no `"use client"` and no fetch, and it hits no row. The table does not cover test code.

**Run:**
- `E2E_CHROMIUM_PATH=/opt/pw-browsers/chromium make check` on the branch: ruff clean; ESLint zero warnings; typecheck passed; pytest 669 passed, 15 skipped; Vitest 25 files, 351 passed; contract check passed; e2e **60 passed, 35 failed** (`home.spec.ts` 1, `keyboard.spec.ts` 4, `reflow.spec.ts` 30), all from `Error: TODO(Ari)` (34) or the Today row on the real clock (1); exit 2. CONFIRMED that it matches the log, and that each open gap reddens only its own tests.
- In a throwaway `git worktree` (removed afterwards) with K1–K3 filled with the plan's code: `make e2e` passed **95 of 95** (2.1 min), with no `destination stream closed early` line. CONFIRMED. I did not re-run `--repeat-each=3`.
- Probes in the same worktree, each reverted, all gone with it: the focus measurement on hand-built pages (finding 2); the F7 stop's geometry, plus the grid with `snap-proximity` and with no snapping (finding 3); J8 with `setOptimistic(next)` removed, then with a stronger assertion (finding 1).
- After every run, 8101, 8102 and 3100 refused connections (checked through bash `/dev/tcp`, because `ss` is not installed here) and no uvicorn, next or proxy process remained. `git status` shows only this file.

**Not run:** the CI job, Node 24, a laptop, mutations M1–M10 (only my own three), the manual pass.

**Counts:** 0 blocker, 3 should-fix, 9 nit. **Verdict: proceed after fixes.** The harness is careful and well documented: the real API, the server-side pin, the proxy, hermetic routing, the ratchet and its unit tests. With the gaps filled, everything ran green here. The three should-fixes are about what the evidence claims:
- J8 cannot fail on the thing it says it proves.
- The focus measurement would pass an invisible "fix" in Step 8.
- F7's recorded cause and fix are wrong, and Ari marks F7 from that table.

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | should-fix | **J8 does not prove that the chip is optimistic.** Its `Proves:` says the chip "is there at once (the optimistic value)". But the chip assertion is a retrying `toBeVisible()` with no bound, and the chip is still there after the navigation lands. So the test passes whether the chip came from `useOptimistic` or from the server's new props 1.5 s later. Fix: after the chip assertion, assert again that the request is still in flight, e.g. `await expect(page.locator('[aria-busy="true"]')).toHaveCount(1, { timeout: 100 })`. Then add this break to the mutation table (B6-M11). | `filter-busy.spec.ts:25-27`; `filter-header.tsx:77,89`. Worktree mutation, `setOptimistic(next)` replaced by `void setOptimistic`: J8 **passed** (J2 too). With the extra assertion: 3 of 3 green unmutated (`--repeat-each=3`), red mutated (`toHaveCount` failed). CONFIRMED | The one browser-level check of B5 fact 12 ("finally observable", plan J8) is vacuous. A regression that drops the optimistic update passes the whole suite | **Fixed.** `filter-busy.spec.ts` re-asserts `aria-busy="true"` inside a 100 ms bound after the chip assertion, so the chip must be visible while the request is still in flight. B6-M11 (`setOptimistic(next)` removed) is in Verification 4 and the log: unmutated 3 of 3 green, mutated red. |
| 2 | should-fix | **The focus measurement credits changes that are not a visible indicator** (the log's "where to look hardest" 2). `measureFocusIndicator` returns the **strongest** changed pixel against the page background, and it has no minimum area. Two cases go wrong. A focus style that darkens text imperceptibly reads as a strong indicator. So does one dark dot. Today every F3 target fails anyway, so the numbers in the findings table stand. The risk is in Step 8: a fix that changes almost nothing can turn the F3 row "stale" (green), and the row is then deleted. Fix: for each changed pixel take the **lower** of its contrast against the background and against the pixel it replaced (the prototype's before/after pair, Departure 6). Then require a minimum count of pixels at or above 3:1, for example a 1px perimeter of the target's box. Add the two cases below as self-tests in the first `describe` | Worktree probe, a button with `outline:none` on white, scored by the unchanged `measureFocusIndicator`: `:focus{color:#222}` (text #000 to #222) → **15.91:1**, 216 pixels changed; `#1a1a1a` → 17.40:1; a single 1px dark dot → **18.73:1**, 4 pixels changed. All three clear the 3:1 line. CONFIRMED | Step 8's red→green for F3 can go green on a change no keyboard user can see, and the ratchet then records it as fixed for good | **Fixed.** `measureFocusIndicator` now scores each changed pixel by the lower of its contrast with the background and with the pixel it replaced, and takes the score an outline's worth of pixels reaches. Both reviewer cases are self-tests, written first and watched fail (15.9 and 21), now green. The area is 90% of a 1px ring (`2(w+h)-4`), not the exact perimeter: the exact count made the Venues box's thin full-strength border count by luck of a few rounded-corner pixels. F3 re-measured: 1.54 (links), 2.05 (Venues box), 1.66 (Month select); all six still below 3:1, so the baseline count is unchanged. |
| 3 | should-fix | **F7's recorded cause and likely fix are refuted.** The findings table says the cause is "scroll-snap `mandatory` against the browser's focus scrolling" and proposes "`scroll-padding` on the row, or `proximity` snapping". Measured: after Tab, the row's `scrollLeft` is still **0**, and it is still 0 after 500 ms. The browser does not scroll the row at all. Replacing `snap-mandatory` with `snap-proximity`, or removing snapping entirely (`snap-x`, `snap-start`), leaves the stop hidden (the 375 test stays green against the row that counts 1). The likelier cause (PLAUSIBLE): Chromium's focus scrolling leaves alone an element that is already partly visible. The link shows 62 of its 128 px. Rewrite F7's cause as unknown, or as this, and its fix as "to investigate" (candidates: make columns narrow enough that a link is never split at 375, or scroll the focused link fully into view, which needs client code in a Server Component grid). Fix this before Ari marks it | Worktree probe at 375 on `/`, stop 16: `9:00 PM – 11:30 PM, show details`, `display: inline-block`, box x 297–425; scroller x 16–359, `scrollWidth` 524, `clientWidth` 343, `scrollLeft` 0; topmost element at the centre is `<main>` (page padding). The same count of 1 with `snap-proximity` and with no snap classes (`keyboard.spec.ts -g sticky`, rebuilt each time). CONFIRMED (the cause stated above is PLAUSIBLE) | Ari marks F7 on a wrong diagnosis, and the fix round tries `proximity` or `scroll-padding`, which do nothing | **Fixed.** F7's row in the findings table now says the cause is unknown, retracts snap-`mandatory`, `scroll-padding` and `proximity` as causes and fixes (the review's measurements are quoted), and offers the Chromium partly-visible hypothesis as PLAUSIBLE with the remaining candidates under "to investigate". |
| 4 | nit | **The Tab-loop test says more than it checks.** (a) Its title is "no Tab stop is hidden under a sticky heading", yet it allows one hidden stop and counts any cover, not only headings. (b) The ratchet holds a **count**, so if F7's stop is fixed and a stop under a sticky heading appears in the same change, the count is still 1 and the test passes, though its `Proves:` says "a NEW hidden stop … fails". The names are already collected, so hold them: for example, assert `hidden` equals the F7 link's name for `/ @375` and `[]` elsewhere, with the baseline row as the record. (c) The coverage matrix credits this journey for 3.2.1 ("focusing a control … never navigates"), but only the Venues test checks the URL. One `await expect(page).toHaveURL(path)` after the loop covers all ~160 stops | `keyboard.spec.ts:27-35,52-59,88`; `a11y-baseline.ts` F7 row; plan, WCAG matrix 3.2.1. CONFIRMED by reading | A sticky-heading regression can hide behind the F7 fix. The matrix claims a 3.2.1 check that covers one control | **Fixed.** (a) The test is renamed "no Tab stop is newly hidden, under a sticky heading or anything else". (b) Hidden stops are held to the baseline by name: each is its own finding (`b6-focus-obscured: <name>`), so a different stop fails even in the change that fixes F7; F7's row is renamed to match. M6 re-run: 4 of 8 red. (c) After the Tab walk the test asserts the URL is unchanged (3.2.1). |
| 5 | nit | **Nothing checks that every baseline row is exercised.** `expectMatchesBaseline` filters `BASELINE` by the caller's label, so a row whose label no test produces is never compared and never goes stale. That happens if a screen leaves `SCREENS`, a width leaves `WIDTHS`, or a label's wording changes on one side only. A Vitest case in `a11y-baseline.test.ts` can assert that every row's `page` is one of the labels the specs build (`SCREENS` × `WIDTHS`, plus the popup, focus and tab-stop labels as one exported list) | `a11y.ts:62-65`; `a11y-baseline.ts` rows; `screens.ts`. CONFIRMED by reading | Dead rows that look like enforced known problems, which is the drift the "stale" half exists to prevent | **Fixed.** `e2e/support/labels.ts` is the one place labels are built (the specs use it), and `a11y-baseline.test.ts` asserts every baseline row's page is one of them. Written first against an empty stub (red, every row an orphan), then green. |
| 6 | nit | **CI can go green while running a subset, and has no time cap.** `playwright.config.ts` has no `forbidOnly: !!process.env.CI`, so a committed `test.only` makes the e2e job pass on one test and switches off every scan. The `e2e` job has no `timeout-minutes`, so the default of 6 hours applies if something hangs outside Playwright's own timeouts | `playwright.config.ts:26-44`; `ci.yml` `e2e` job. CONFIRMED by reading | An enforcement job that can pass while enforcing nothing | **Fixed.** `forbidOnly: !!process.env.CI` in `playwright.config.ts`; `timeout-minutes: 20` on the `e2e` job. |
| 7 | nit | **`fake-now.mjs` does not check its input.** If `E2E_FROZEN_NOW` is unset or malformed, `FROZEN` is `NaN`. Once K1 is filled, `Date.now()` returns `NaN`, `Temporal.Now` throws, and every page 500s far from the cause. A guard in the written part, outside the gap, makes it loud: `if (Number.isNaN(FROZEN)) throw new Error("E2E_FROZEN_NOW is not an ISO instant")`. Today only the config sets the variable, so this guards a future edit | `fake-now.mjs:31`. CONFIRMED by reading; the `Temporal.Now` failure on `NaN` is PLAUSIBLE (not run) | A confusing all-red suite after an edit to `clock.ts` or the config | **Fixed.** `fake-now.mjs` throws at startup when `E2E_FROZEN_NOW` is missing or not a date, in the written part outside the gap. The scaffold's `eslint-disable` for an unused `FROZEN` is gone too (the guard reads it), so lint is clean with the gap open and filled. |
| 8 | nit | **The skeleton's unit test breaks two of the project's own rules.** (a) It finds the bars with a class selector, `.animate-pulse`, which the B5 rule ("role, name or label, never a class", `apps/calendar/AGENTS.md`) forbids. `[aria-hidden="true"]` is an ARIA state, the same exception the suite already makes for `aria-busy`. (b) The first test is named "announces that shows are loading", while D8, the component's docstring and the test's own comment say no announcement is promised. Rename it to something like "exposes a 'Loading shows' status" | `calendar-skeleton.test.tsx:18,30`; `calendar-skeleton.tsx:7-15`. CONFIRMED by reading | The test teaches the class-selector habit, and its name repeats the claim that review finding 11 removed | **Fixed.** The skeleton test finds the hidden group by `[aria-hidden="true"]` (and checks the status is not inside one), and the first test is renamed "exposes a 'Loading shows' status", with the no-announcement caveat in its comment. |
| 9 | nit | **Some cross-references are not in the scoped form.** `ci.yml:142` "D1 and D4"; `a11y-baseline.ts:61-62` "F1", "F2"; "(B6 plan, D2)", "(B6 plan D8, …)", "(B6 plan, K1)", "(B6 plan, D6)" in `clock.ts`, `clock.test.ts`, `calendar-skeleton.tsx`, `calendar-skeleton.test.tsx`, `fake-now.mjs`, `reflow.ts`, `reflow.spec.ts`, `a11y-baseline{,.test}.ts`. Meanwhile `playwright.config.ts` and others use `B6-D1`/`B6-D3`. The forms are `B6-D2`, `B6-F1`, `B6-K1` | `conventions.md` check command, run over the diff's files. CONFIRMED | `grep` for `B6-D2` misses half the citations, and the check command reports them | **Fixed.** `B6 plan, D2`, `B6 plan D8`, `B6 plan, K1`, `B6 plan, D6`, `D1 and D4`, and the bare `F1`/`F2`/`F7` in the baseline and keyboard comments are now `B6-D2`, `B6-D8`, `B6-K1`, `B6-D6`, `B6-D1 and B6-D4`, `B6-F1`, `B6-F2`, `B6-F7` (in `clock.ts`, `clock.test.ts`, `fake-now.mjs`, `reflow.ts`, `reflow.spec.ts`, `calendar-skeleton.tsx`, `a11y-baseline{,.test}.ts`, `keyboard.spec.ts`, `ci.yml`). References like "B6 plan, Step 6" name a section, not an ID, and stay. |
| 10 | nit | **`next build` type-checks `e2e/` and `playwright.config.ts`** (log, "where to look hardest" 6; `notes.md`). `check-types` in CI already catches the same errors, so the extra cost is that a Vercel preview build fails on test-only code. One option: `typescript.tsconfigPath` in `next.config` pointing at a build tsconfig that excludes `e2e/**` and `playwright.config.ts`, with `check-types` keeping the full one. Or leave it and keep the `notes.md` entry, which is a fair choice | `tsconfig.json` `include: **/*.ts`; log. That `tsconfigPath` fits here is PLAUSIBLE (not tried) | A preview deploy breaks on a spec typo | **Rejected.** `next build` type-checking `e2e/` costs a Vercel preview a failure on a spec typo, but `check-types` and CI catch the same error first, a build-only `tsconfigPath` adds a second tsconfig to keep in step (untried here), and the `notes.md` entry already warns. Revisit if a spec typo ever reaches a preview. |
| 11 | nit | **The log and the plan body disagree in small ways.** (a) "`incomplete` triage (13 pages, 2 widths)", but `SCREENS` has 15, plus the error screen. (b) Departure 5 says "the plan's gap text says so", but the plan body's K2 *Check* still reads "green on the real page at 1280 and 375, on `/` and on `/venue/1`", with no F7 row. Only the source block was updated. (c) `react-hooks/rules-of-hooks` is switched off for `e2e/**/*.ts` (`eslint.config.js`), but no departure lists it (only `notes.md` does). (d) Verification 3's `ss -ltn` does not exist in this sandbox (`ss: command not found`). The log used `curl`, and the plan's command could say so | Log round 2; plan K2; `eslint.config.js:12-17`; `make check` output. CONFIRMED | Ari or the next session reads a number or rule that is not what was built | **Fixed.** (a) the incomplete-triage line is corrected; (b) K2's *Check* in the plan body now names the F7 baseline row; (c) Departure 12 lists the `react-hooks` rule change; (d) Verification 3 uses `curl`, with a note that `ss` is not installed. Corrections to the log are marked as such in place. |
| 12 | nit | **The teardown's in-flight wait lets a hung request go without a trace** (log, "where to look hardest" 3). The `.catch(() => {})` is right not to fail the test. But when the 5 s run out, recording the URLs still in flight (`test.info().annotations.push(...)` or a `console.warn`) would make a real hang visible in the report rather than invisible | `support/test.ts:96-99`. CONFIRMED by reading | A server request that never completes, which is itself a bug, goes unnoticed | **Fixed.** When the five seconds run out, the fixture records the URLs still in flight as a test annotation (`requests still in flight at teardown`) instead of dropping them silently; it still does not fail the test. |

Rejected: #10 (a build-only tsconfig is more to maintain than the risk it removes; the warning is in `notes.md`).

**Test-suite result after the fixes** (Node 22.22.0, `E2E_CHROMIUM_PATH=/opt/pw-browsers/chromium`): `make check` exit 2, red only through the three open gaps: ruff clean, ESLint zero warnings, typecheck passed, pytest 669 passed and 15 skipped, Vitest **352 passed** (25 files; +1 for the orphan-row test), contract current, e2e **62 passed, 35 failed** (1 K1, 4 K2, 30 K3; every failure `TODO(Ari)` or the Today row on the real clock), no `destination stream closed early` line. With K1–K3 filled with the plan's code in a fresh throwaway worktree: **97 of 97** green and `pnpm lint` clean. B6-M6 (red 4 of 8) and the new B6-M11 (red) re-run there; the worktree is removed and nothing is left on 8101, 8102 or 3100.

## Implementation log, round 3

### Round 3 — the code review fixes (Claude Sonnet 5.5, October 20, 2026)

**Scope:** the fixes for code review round 1 only, on top of `eea430c`. Files: `e2e/filter-busy.spec.ts`, `e2e/focus-indicator.spec.ts`, `e2e/keyboard.spec.ts`, `e2e/a11y-screens.spec.ts`, `e2e/a11y-popups.spec.ts`, `e2e/support/{focus.ts,labels.ts (new),screens.ts,a11y-baseline.ts,a11y-baseline.test.ts,fake-now.mjs,test.ts,clock.ts,clock.test.ts,reflow.ts}`, `e2e/reflow.spec.ts`, `playwright.config.ts`, `.github/workflows/ci.yml`, `app/_components/calendar-skeleton.{tsx,test.tsx}`, and this plan.

**Departures from the code review's suggestions:** finding 2 used 90% of a one-pixel ring as the minimum area instead of "a 1px perimeter" (reason in its Resolution); finding 4 held the stops by name inside the ratchet's rule id instead of a separate expected-names list, so one source records both; finding 10 was rejected.

**`TODO(Ari)` gaps:** still all three open (K1 `fake-now.mjs`, K2 `focus.ts`, K3 `reflow.ts`; line numbers moved by a few lines, the links in round 2 point at the right files). No gap was filled on the branch.

**Verification:** as in the line above ("Test-suite result after the fixes").

**Where to look hardest:** (1) the focus measurement's 90% allowance and the rule "lower of two contrasts" (`e2e/support/focus.ts`): the F3 numbers moved with it (1.54 to 2.58 became 1.54 to 2.05), and the baseline holds counts, so a ring near 3:1 is now sensitive to both choices; (2) F7 is still undiagnosed; (3) the CI job has still never run.

