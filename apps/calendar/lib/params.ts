/**
 * URL state: turning what's in the address bar into typed values, and back.
 *
 * Two kinds of input arrive from the URL, and both are USER INPUT — a
 * bookmark from last month, a hand-edited address, a link someone
 * mangled — so every parser here is total: bad input becomes `null` or is
 * dropped, never a throw. A throw in a page's render is a 500 (the error
 * boundary); the right answer to `/venue/abc` is a 404 and to
 * `/?venue=abc` is the ordinary calendar.
 *
 *   1. Path params (`/venue/[id]`, `/day/[date]`):  parseIdParam, parseDateParam
 *   2. Search params (`/?venue=1&venue=3&month=2026-10`):
 *        parseCalendarFilters -> toShowsQuery -> (lib/api.ts getShows)
 *        buildCalendarHref goes the other way, filters -> URL
 *
 * Filters live in the URL, not component state (arch-initial.md §4): that
 * is what makes a filtered calendar shareable, bookmarkable and
 * server-renderable. The price is exactly this file — the URL has to be
 * parsed defensively and written canonically (one filter set, one URL).
 *
 * Pure functions with no env and no fetch, so they're unit tested without
 * mocks (params.test.ts). Not `server-only`. B3's filter header, a Client
 * Component, builds hrefs too, but imports them from lib/calendar-href.ts
 * (Temporal-free) rather than from here, where the polyfill would ride along.
 */

// Explicit import: Node 24 has no global Temporal, so the polyfill is the
// implementation. Temporal, not Date — `new Date("2026-09-28")` parses as
// UTC midnight and renders as the 27th west of Greenwich (api-contract.md §3).
import { Temporal } from "@js-temporal/polyfill";
import type { CalendarFilters } from "./calendar-href";

// `CalendarFilters` and `buildCalendarHref` live in lib/calendar-href.ts so
// a Client Component can import them without pulling in Temporal (B3).
// Re-exported here so every existing import keeps working.
export { buildCalendarHref } from "./calendar-href";
export type { CalendarFilters } from "./calendar-href";

// What Next hands a page as `searchParams` (after `await`): a key that
// appears once is a string, a repeated key is a string[], an absent key is
// undefined. Declared here rather than imported so tests and non-page
// callers don't need Next's generated PageProps.
export type SearchParams = { [key: string]: string | string[] | undefined };

// What `getShows` (lib/api.ts) is called with. `start` / `end` are
// inclusive ISO dates. The home calendar sends both together (a month) or
// neither (the server's default window); the venue page's paging sends a
// `start` ALONE on purpose, and the server fills in `end` so the window
// length stays its decision. `upcoming` (the artist page) means "every
// show from the server's today"; it is exclusive with `start`/`end`, which
// the SERVER enforces with a 422 — this type doesn't try to repeat the rule.
export type ShowsQuery = {
  start?: string;
  end?: string;
  venueIds: number[];
  artistIds: number[];
  upcoming?: boolean;
};

// --- path params ---------------------------------------------------------------

// Database ids are Postgres `integer` (int4) — Mapped[int] in
// app/db/models/calendar.py. A bigger number can only ever be an
// out-of-range error from the database (a 500 once the routers are
// DB-backed), where "no such record" -> 404 is the right answer.
const MAX_ID = 2147483647;

/**
 * "12" -> 12. Anything that isn't a canonical positive int4 -> null.
 *
 * The regex does the work `Number()` can't be trusted with: Number(" 12"),
 * Number("1e3") and Number("") all "succeed". It also rejects leading
 * zeros so `/venue/012` isn't a second URL for `/venue/12`.
 */
export function parseIdParam(raw: string): number | null {
  if (!/^[1-9]\d*$/.test(raw)) return null;
  const id = Number(raw);
  // 20-digit strings lose precision as a double, but they're far above
  // MAX_ID either way, so the comparison is still right.
  return id <= MAX_ID ? id : null;
}

/**
 * "2026-10-08" -> that PlainDate. Anything else -> null.
 *
 * Three layers, each catching something the others miss:
 *   1. A strict YYYY-MM-DD regex FIRST. `Temporal.PlainDate.from` happily
 *      accepts "20261008" and "2026-10-08T00:00", which would make
 *      `/day/20261008` and `/day/2026-10-08T…` extra URLs for one page.
 *   2. Temporal itself, which throws on impossible dates ("2026-02-30",
 *      "2026-02-29") for string input regardless of its `overflow` option.
 *   3. Year >= 1. "0000-01-01" passes both of the above, but the API
 *      rejects year 0 with a 422, which would surface as the error page
 *      instead of a 404 (plan review #8). "0001-01-01" the API accepts.
 */
export function parseDateParam(raw: string): Temporal.PlainDate | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return null;
  let date: Temporal.PlainDate;
  try {
    date = Temporal.PlainDate.from(raw);
  } catch {
    return null;
  }
  return date.year >= 1 ? date : null;
}

// --- search params -------------------------------------------------------------

/**
 * "2026-10" -> "2026-10"; anything else (including undefined) -> null.
 *
 * Returns the validated STRING rather than a Temporal object because the
 * string is the canonical URL form — it goes straight back into
 * buildCalendarHref — and `toShowsQuery` converts to a range when it
 * needs one. Year >= 1 for the same reason as parseDateParam.
 */
export function parseMonthParam(raw: string | undefined): string | null {
  if (raw === undefined) return null;
  const match = /^(\d{4})-(0[1-9]|1[0-2])$/.exec(raw);
  if (match === null || Number(match[1]) < 1) return null;
  return raw;
}

/**
 * Parses ONE repeatable id key (`venue`, `artist`) into a canonical list.
 *
 * Next hands search params over as `string | string[] | undefined` — one
 * `venue=1` is a string, a repeated key is an array — and the API contract
 * also uses repeated keys (api-contract.md §2). The URL is the state
 * (arch-initial.md §4), so parsing is TOTAL (bad entries are dropped one by
 * one, never a throw) and CANONICAL (de-duplicated and sorted numerically, as
 * a bare `.sort()` is lexicographic and would give [10, 9]) so that one filter
 * set has exactly one URL.
 */
function parseIdList(value: string | string[] | undefined): number[] {
  const asList = (v: string | string[] | undefined) =>
     v === undefined ? [] : Array.isArray(v) ? v : [v];
  return [...new Set(asList(value).map(parseIdParam).filter((n): n is number => n !== null))].sort((a, b) => a - b);
}

/**
 * The page's `searchParams` -> typed filters. Never throws; an unknown or
 * malformed key is ignored (a stale bookmark must still render).
 */
export function parseCalendarFilters(searchParams: SearchParams): CalendarFilters {
  // `month` may repeat (`?month=a&month=b`). Take the first VALID one, so
  // a bad first value doesn't hide a good second one.
  const months =
    searchParams.month === undefined
      ? []
      : [searchParams.month].flat();
  return {
    venueIds: parseIdList(searchParams.venue),
    artistIds: parseIdList(searchParams.artist),
    month: months.map(parseMonthParam).find((m) => m !== null) ?? null,
  };
}

/**
 * "2026-10" -> the first and last day of that month, as inclusive ISO
 * dates. The input must already be valid (parseMonthParam).
 *
 * `month=2026-10` becomes the API's inclusive `start`/`end`. The client does
 * calendar ARITHMETIC but consults no clock (decision D2; api-contract.md §3
 * "the server owns now"), so a month means the whole month, past days
 * included. Temporal, not `Date`: month lengths and leap Februaries are
 * exactly what `Date` arithmetic gets subtly wrong. `end` is the last day of
 * the month rather than the first of the next, because the API's `end` is
 * inclusive.
 */
function monthRange(month: string): { start: string; end: string } {
  const ym = Temporal.PlainYearMonth.from(month);
  return {
    start: ym.toPlainDate({ day: 1 }).toString(),
    end: ym.toPlainDate({ day: ym.daysInMonth }).toString(),
  };
}

/**
 * Filters -> the arguments `getShows` takes. With no month, `start`/`end`
 * are left OUT so the server chooses its default window (the next four
 * weeks, by the metro's clock). With a month, both are always sent
 * together, so the API's default window and its MAX_RANGE never apply.
 */
export function toShowsQuery(filters: CalendarFilters): ShowsQuery {
  const query: ShowsQuery = {
    venueIds: filters.venueIds,
    artistIds: filters.artistIds,
  };
  if (filters.month !== null) {
    Object.assign(query, monthRange(filters.month));
  }
  return query;
}

/**
 * The venue page's `?from=YYYY-MM-DD` (B4): where its embedded calendar
 * starts. A valid date -> that string (it goes straight into the API's
 * `start`); anything else -> `null`, meaning "the server's default
 * window". A repeated key takes the first VALID value, like
 * `parseMonthParam`.
 *
 * Same strictness as `parseDateParam` (which it calls), plus one more
 * bound: year <= 9998. The API fills `end = start + 27 days`, and
 * `9999-12-20 + 27 days` overflows Python's `date` (max 9999-12-31) and
 * answers 500. A search param must never cause a 500 (see this file's
 * docstring), so such a value is ignored here instead.
 */
export function parseFromParam(raw: string | string[] | undefined): string | null {
  const candidates = raw === undefined ? [] : Array.isArray(raw) ? raw : [raw];
  for (const candidate of candidates) {
    const date = parseDateParam(candidate);
    if (date !== null && date.year <= 9998) return candidate;
  }
  return null;
}
