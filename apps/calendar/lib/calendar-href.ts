/**
 * Filter state <-> URL, split out of lib/params.ts so a CLIENT component
 * can import it.
 *
 * lib/params.ts imports the Temporal polyfill at module scope (for the
 * date and month parsers). The calendar's filter header is a Client
 * Component that must build hrefs, and importing them from params.ts
 * would ship ~36 KB gzipped of Temporal to every visitor for a function
 * that only joins strings. So the type and the writer live here, with no
 * dependencies, and params.ts re-exports them (nothing that imported them
 * from there changes). B2's params.ts docstring anticipated this caller:
 * "B3's filter header will build hrefs from a Client Component".
 *
 * Keep this file import-free (types aside). params.test.ts and
 * calendar-href.test.ts cover it.
 */

// The calendar's filter state. `venueIds` / `artistIds` are canonical:
// de-duplicated and ascending. `month` is "YYYY-MM" or null (no month
// filter -> the server's default four-week window).
export type CalendarFilters = {
  venueIds: number[];
  artistIds: number[];
  month: string | null;
};

/**
 * Filters -> the canonical href: `/` when empty, otherwise
 * `/?venue=1&venue=3&artist=7&month=2026-10`, keys always in that order.
 *
 * The write side of `parseCalendarFilters` (lib/params.ts). Together they
 * make the URL a faithful serialisation of the filter state. Callers pass
 * canonical filters (as parseCalendarFilters returns, or `withIds`
 * produces) — this doesn't re-sort.
 */
export function buildCalendarHref(filters: CalendarFilters): string {
  const params = new URLSearchParams();
  for (const id of filters.venueIds) params.append("venue", String(id));
  for (const id of filters.artistIds) params.append("artist", String(id));
  if (filters.month !== null) params.append("month", filters.month);
  const queryString = params.toString();
  return queryString ? `/?${queryString}` : "/";
}

/**
 * `filters` with one id list replaced, in canonical form.
 *
 * A multi-select reports ids in the order they were picked; the URL needs
 * one canonical form per filter set (so a shared link is the same link
 * however it was reached), de-duplicated and sorted NUMERICALLY (a bare
 * `.sort()` is lexicographic: [10, 9]). Returns a new object.
 */
export function withIds(
  filters: CalendarFilters,
  key: "venueIds" | "artistIds",
  ids: number[],
): CalendarFilters {
  return { ...filters, [key]: [...new Set(ids)].sort((a, b) => a - b) };
}
