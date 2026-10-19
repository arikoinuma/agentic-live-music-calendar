/**
 * The list of screens the suite checks (B6 plan, Step 5): every route and the states of
 * it worth a separate look. Shared by the accessibility scan and the reflow check, so
 * "every screen" means the same list in both.
 *
 * Where the expected values come from: titles are written from the formats in the code
 * (the layout's `%s · Agentic Live Music Calendar` template; the show format in B4-D7:
 * `<artists> at <venue>, <weekday, month day, year>`) and the sample data (apps/api/app/
 * sample_data.py), never copied from what a page printed. A mismatch is investigated.
 */
import type { Page } from "@playwright/test";
import { expect } from "./test";

export const SITE = "Agentic Live Music Calendar";
export const WIDTHS = [1280, 375]; // desktop; a phone

export type Screen = {
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

export const SCREENS: Screen[] = [
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
