/**
 * Accessibility scan of EVERY screen, at desktop and phone width (B6 plan, Step 5).
 *
 * The requirement is "every screen meets WCAG 2.2 AA" (requirements-initial.md), so
 * one test per screen per width, each held to the ratchet baseline
 * (e2e/support/a11y-baseline.ts). Each test also asserts the page's exact browser
 * title (WCAG 2.4.2, Page Titled), since the page is already loaded and the title is
 * cheap to check.
 *
 * Where the expected values come from: titles are written from the formats in the code
 * (the layout's `%s · Agentic Live Music Calendar` template; the show format in B4-D7:
 * `<artists> at <venue>, <weekday, month day, year>`) and the sample data (apps/api/app/
 * sample_data.py), never copied from what a page printed. A mismatch is investigated.
 */
import type { Page } from "@playwright/test";
import { expectBaseline } from "./support/a11y";
import { expect, test } from "./support/test";

const SITE = "Agentic Live Music Calendar";
const WIDTHS = [1280, 375]; // desktop; a phone

type Screen = {
  path: string;
  /** Waits until the page's real content is there, so a scan never sees a skeleton. */
  ready: (page: Page) => Promise<void>;
  title: string;
};

const heading = (name: string) => (page: Page) =>
  expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
const calendar = (articles: number) => async (page: Page) => {
  await heading("Live music")(page);
  await expect(page.getByRole("article")).toHaveCount(articles);
};

const SCREENS: Screen[] = [
  // The calendar: plain, filtered to one venue (8 of the 25 shows), and a filter with no matches.
  { path: "/", ready: calendar(25), title: SITE },
  { path: "/?venue=1", ready: calendar(8), title: SITE },
  {
    path: "/?venue=2&artist=1", // Midway + Charlie Parr: no shows
    ready: async (page) => {
      await heading("Live music")(page);
      await expect(page.getByText("No matches found.")).toBeVisible();
    },
    title: SITE,
  },
  // The day view, in its three orders (Wed, Oct 7: five shows).
  { path: "/day/2026-10-07", ready: heading("Wed, Oct 7, 2026"), title: `Wed, Oct 7, 2026 · ${SITE}` },
  { path: "/day/2026-10-07?sort=time", ready: heading("Wed, Oct 7, 2026"), title: `Wed, Oct 7, 2026 · ${SITE}` },
  { path: "/day/2026-10-07?sort=artist", ready: heading("Wed, Oct 7, 2026"), title: `Wed, Oct 7, 2026 · ${SITE}` },
  // Venue and artist pages, and their list pages.
  { path: "/venue/1", ready: heading("The White Squirrel Bar"), title: `The White Squirrel Bar · ${SITE}` },
  { path: "/venues", ready: heading("Venues"), title: `Venues · ${SITE}` },
  { path: "/artist/1", ready: heading("Charlie Parr"), title: `Charlie Parr · ${SITE}` },
  { path: "/artists", ready: heading("Artists"), title: `Artists · ${SITE}` },
  // Shows: timed with several acts (2), untimed (3: Tarnation at Midway, no start time), and
  // one with a start time and no end (22: Lanue at White Squirrel, 6:00 PM).
  {
    path: "/show/2",
    ready: heading("Nooky Jones, Beasthead"),
    title: `Nooky Jones, Beasthead at Zhora Darling, Wed, Sep 30, 2026 · ${SITE}`,
  },
  { path: "/show/3", ready: heading("Tarnation"), title: `Tarnation at The Midway Saloon, Wed, Sep 30, 2026 · ${SITE}` },
  { path: "/show/22", ready: heading("Lanue"), title: `Lanue at The White Squirrel Bar, Wed, Oct 7, 2026 · ${SITE}` },
  // The diagnostics page, and the 404 page (no metadata of its own, so the site title).
  { path: "/health", ready: heading("Status"), title: `Status · ${SITE}` },
  { path: "/nope", ready: heading("Not found"), title: SITE },
];

for (const width of WIDTHS) {
  for (const screen of SCREENS) {
    // Proves: this screen, at this width, has no accessibility violation beyond the
    // baseline's (a new one fails; so does a fixed one the baseline still lists), and
    // its browser title is the exact expected text.
    test(`${screen.path} has no new accessibility violations @${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await page.goto(screen.path);
      await screen.ready(page);

      await expect(page).toHaveTitle(screen.title);
      await expectBaseline(page, `${screen.path} @${width}`);
    });
  }

  // Proves: the error screen (what a visitor sees when the API is down) is accessible
  // too. The delay proxy answers 502 to everything, the home page's body throws, and
  // after hydration the app's error boundary takes over its region (app/error.tsx).
  // The title stays the site's.
  test(`the error screen has no new accessibility violations @${width}`, async ({ page, stack }) => {
    await stack.fail();
    await page.setViewportSize({ width, height: 800 });
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1, name: "Something went wrong" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();

    await expect(page).toHaveTitle(SITE);
    await expectBaseline(page, `/ (API down) @${width}`);
  });
}
