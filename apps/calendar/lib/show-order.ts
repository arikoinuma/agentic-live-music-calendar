/**
 * The day view's three orderings, and the artist page's chronological
 * order (B4 plan, D6 and "Test approach §1").
 *
 * `/day/[date]` lets the reader choose how to view one night
 * (requirements-initial.md, "/Day view"): by venue by alpha (the default),
 * by venue by time, or by artist by alpha. The mode lives in the URL
 * (`?sort=time`, `?sort=artist`; the default is the bare URL) like every
 * other view state (arch-initial.md §4), so it is shareable and survives
 * Back. The API returns flat shows and leaves grouping to the frontend
 * (routers/shows.py: "the day view needs three different groupings of
 * identical data"), which is why this module exists.
 *
 * Pure. It imports `nightSortKey` from lib/dates.ts (Temporal), so it is
 * server-side in practice, like lib/calendar.ts.
 */

import { nightSortKey } from "./dates";
import { todo } from "./todo";
import type { ShowSummary } from "./types";

export type DaySort = "venue" | "time" | "artist";

/** One line of artist mode: an act, where, and when. */
export type ArtistRow = {
  artist: { id: number; name: string };
  venue: { id: number; name: string };
  showId: number;
  date: string;
  // The act's own set time when the listing has one, else the show's, else
  // null ("not stated"). A clock time, formatted by the page with
  // `formatShowTime(date, time)` so a 1:00 AM act reads "1:00 AM Thu".
  time: string | null;
};

// Venue names compare alphabetically as written (the API sorts venues the
// same way): no "The"-stripping, so "The Midway Saloon" files under T.
// A fixed locale, as lib/calendar.ts uses, so the order doesn't vary with
// the server's environment.
const byVenueName = (a: ShowSummary, b: ShowSummary): number =>
  a.venue.name.localeCompare(b.venue.name, "en-US");

// --- venue modes (Gap D) ------------------------------------------------------------

/*
 * TODO(Ari) — Gap D. Lesson: "by venue" and "by time" are the SAME two keys
 *   in opposite priority. A comparator chain is `primary || secondary`:
 *   a tie returns 0, 0 is falsy, so `||` falls through to the next key.
 *   The time key is `nightSortKey`, not the clock — the 1:00 AM show is the
 *   END of the night (requirements-initial.md, "Times after midnight").
 *   `byVenueName` is written above.
 * Code (replace both `todo` lines; delete `import { todo } from "./todo"`
 *   once no gap in this file still calls it — Gap C does too):
 *   export const venueOrder = (a: ShowSummary, b: ShowSummary): number =>
 *     byVenueName(a, b) || nightSortKey(a.start_time) - nightSortKey(b.start_time);
 *   export const timeOrder = (a: ShowSummary, b: ShowSummary): number =>
 *     nightSortKey(a.start_time) - nightSortKey(b.start_time) || byVenueName(a, b);
 * Check: `pnpm --filter calendar test show-order` — venue order
 *   [25, 8, 22, 23, 24] and time order [22, 24, 8, 23, 25] on the fixture
 *   day. Likeliest mistakes: comparing `a.start_time < b.start_time` as
 *   strings (puts 01:00 first), or `&&` instead of `||` (every non-tie then
 *   returns the second key).
 */
// (`byVenueName` is passed in only so it counts as used while the gap is open.)
export const venueOrder = (a: ShowSummary, b: ShowSummary): number => todo(byVenueName, a, b);
export const timeOrder = (a: ShowSummary, b: ShowSummary): number => todo(byVenueName, a, b);

// --- artist mode (Gap C) ------------------------------------------------------------

/**
 * One row per ACT, alphabetical by artist, an artist's own rows in night
 * order.
 *
 * TODO(Ari) — Gap C. Lesson: artist mode isn't a different SORT of the
 *   same list — it's a different SHAPE. A three-act bill becomes three
 *   rows, and an artist on two bills the same night gets two. That is why
 *   the API returns flat shows and leaves grouping to the frontend
 *   (routers/shows.py). `flatMap` makes the shape; then the sort. Each
 *   row's time is the act's own when the listing gave one, else the show's.
 * Code (replace the `todo` line below):
 *   const rows = shows.flatMap((show) =>
 *     show.lineup.map((entry) => ({
 *       artist: entry.artist,
 *       venue: show.venue,
 *       showId: show.id,
 *       date: show.date,
 *       time: entry.start_time ?? show.start_time ?? null,
 *     })),
 *   );
 *   return rows.sort(
 *     (a, b) =>
 *       a.artist.name.localeCompare(b.artist.name, "en-US") ||
 *       nightSortKey(a.time) - nightSortKey(b.time),
 *   );
 * Check: `pnpm --filter calendar test show-order` — the 8-row fixture case
 *   and the same-artist-twice case. Likeliest mistakes: `map` instead of
 *   `flatMap` (an array of arrays; the type error says so), or the show's
 *   time for every act (Pert Near Sandstone at 22:00 instead of 23:15).
 */
export function artistRows(shows: ShowSummary[]): ArtistRow[] {
  return todo(shows);
}

// --- the URL ----------------------------------------------------------------------------

/**
 * `?sort=` -> a mode. Anything unrecognised, empty or missing is the
 * default ("venue"), never an error: a search param isn't part of the
 * resource's identity, so `/day/2026-10-07?sort=bogus` is just the day. A
 * repeated key takes the first VALID value, as `parseMonthParam` does.
 */
export function parseDaySort(raw: string | string[] | undefined): DaySort {
  const candidates = raw === undefined ? [] : Array.isArray(raw) ? raw : [raw];
  for (const candidate of candidates) {
    if (candidate === "venue" || candidate === "time" || candidate === "artist") return candidate;
  }
  return "venue";
}

/**
 * The canonical URL for a view: the default has NO query, so each view has
 * exactly one URL (`?sort=venue` is accepted on the way in, never written).
 */
export function dayHref(date: string, sort: DaySort): string {
  return sort === "venue" ? `/day/${date}` : `/day/${date}?sort=${sort}`;
}

/**
 * Chronological: by date, then by night order within a date (a 1:00 AM
 * show after the evening's). The artist page's order; the API sorts by
 * clock time, which would put the 1:00 AM show first in its day. Returns
 * a new array; `sort` is stable.
 */
export function inNightOrder(shows: ShowSummary[]): ShowSummary[] {
  return [...shows].sort(
    (a, b) =>
      a.date.localeCompare(b.date) || nightSortKey(a.start_time) - nightSortKey(b.start_time),
  );
}
